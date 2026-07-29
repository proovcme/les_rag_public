"""Design tokens and component styles for the canonical Sovushka UI kit."""

UIKIT_CSS = """
<style id="sovushka-uikit">
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
  --sov-ui-border: 1px solid var(--border);
  --sov-ui-radius-control: 8px;
  --sov-ui-radius-card: 8px;
  --sov-ui-hit: 40px;
  --sov-ui-icon-column: 20px;
  --sov-ui-icon-gap: 8px;
  --sov-ui-shadow-card:
    0 1px 2px rgba(20, 52, 34, .05),
    0 5px 16px rgba(20, 52, 34, .035);
  --sov-ui-shadow-focus: 0 0 0 3px color-mix(in srgb, var(--accent) 24%, transparent);
}

html {
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* Preserve spatial continuity between the two same-origin AppShell routes.
   Unsupported WebViews ignore this block and keep normal navigation. */
@view-transition {
  navigation: auto;
}

::view-transition-old(root) {
  animation: sov-route-out 130ms ease-in both;
}

::view-transition-new(root) {
  animation: sov-route-in 180ms cubic-bezier(.2, 0, 0, 1) both;
}

@keyframes sov-route-out {
  to {
    opacity: .96;
    transform: translateY(-4px);
  }
}

@keyframes sov-route-in {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
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

.sov-ui-panel,
.sov-ui-card,
.sov-ui-evidence-card {
  min-width: 0;
  border: var(--sov-ui-border);
  border-radius: var(--sov-ui-radius-card);
  background: var(--card-bg);
}

.sov-ui-panel {
  padding: var(--sov-ui-space-4);
}

.sov-ui-panel--plain {
  box-shadow: none;
}

.sov-ui-panel--raised,
.sov-ui-card,
.sov-ui-evidence-card {
  box-shadow: var(--sov-ui-shadow-card);
}

.sov-ui-panel--inset {
  background: var(--bg-mod);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--border) 28%, transparent);
}

.sov-ui-section-heading {
  min-width: 0;
  gap: var(--sov-ui-space-1) !important;
}

.sov-ui-section-title {
  color: var(--text);
  font-size: 14px;
  font-weight: 750;
  line-height: 1.3;
}

.sov-ui-section-detail {
  color: var(--dim);
  font-size: var(--sov-ui-font-size-meta);
  font-weight: 400;
  line-height: 1.45;
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

.sov-ui-shell .q-field__native::placeholder {
  color: var(--dim);
  opacity: .9;
}

.sov-ui-shell .q-btn__content,
.sov-ui-shell .q-tab__label {
  font-size: var(--sov-ui-font-size-control);
  font-weight: 650;
  line-height: var(--sov-ui-line-control);
}

.sov-acronym-identity {
  display: flex;
  min-width: 0;
  gap: 9px;
  align-items: center;
  flex-wrap: nowrap;
}

.sov-acronym-mark {
  flex: 0 0 auto;
  color: var(--accent);
  font-size: 22px;
}

.sov-acronym-copy {
  min-width: 0;
  gap: 0 !important;
}

.sov-acronym-title {
  max-width: 100%;
  overflow: hidden;
  color: var(--accent);
  font-family: var(--sov-ui-font-prose);
  font-size: 14px;
  font-weight: 800;
  line-height: 1.25;
  letter-spacing: .015em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sov-acronym-expansion {
  max-width: 100%;
  overflow: hidden;
  color: var(--dim);
  font-family: var(--sov-ui-font-prose);
  font-size: var(--sov-ui-font-size-meta);
  font-weight: 400;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sov-acronym-identity--compact {
  gap: 6px;
}

.sov-acronym-identity--compact .sov-acronym-mark {
  font-size: 20px;
}

.sov-acronym-identity--compact .sov-acronym-expansion {
  font-size: 11px;
}

.sov-surface-heading {
  color: var(--text);
  font-family: var(--sov-ui-font-prose);
  font-size: 13px;
  font-weight: 750;
  line-height: 1.3;
}

.sov-acronym-preference {
  width: 100%;
  min-height: 40px;
  margin-bottom: 10px;
  padding: 4px 8px;
  border-radius: 8px;
  color: var(--text);
  background: color-mix(in srgb, var(--bg-mod) 72%, transparent);
  font-family: var(--sov-ui-font-prose);
  font-size: var(--sov-ui-font-size-control);
}

.sov-hide-acronym-expansions .sov-acronym-expansion,
.sov-hide-acronym-expansions .sov-chat-subtitle {
  display: none !important;
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
  max-width: min(320px, 36vw);
  align-items: center;
  gap: 9px;
}

.sov-ui-shell .sov-chat-identity-copy {
  display: flex;
  min-width: 0;
  max-width: 100%;
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
  color: var(--accent);
  font-family: var(--sov-ui-font-prose);
  font-size: 14px;
  font-weight: 800;
  line-height: 1.25;
  letter-spacing: 0;
}

.sov-ui-shell .sov-chat-subtitle {
  display: block;
  max-width: 100%;
  overflow: hidden;
  font-family: var(--sov-ui-font-prose);
  font-size: var(--sov-ui-font-size-meta);
  font-weight: 400;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sov-ui-header {
  position: relative;
  z-index: 20;
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
}

.sov-ui-button,
.sov-ui-input .q-field__control,
.sov-ui-select .q-field__control,
.sov-ui-source-chip {
  min-height: var(--sov-ui-hit);
  border-radius: var(--sov-ui-radius-control);
}

.sov-ui-button,
.sov-ui-source-chip {
  transition: background-color .16s ease, border-color .16s ease,
    box-shadow .16s ease, color .16s ease, transform .12s ease;
}

.sov-ui-button {
  min-width: 40px;
  padding: 0 13px !important;
  border: var(--sov-ui-border) !important;
  color: var(--text) !important;
  background: var(--bg-panel) !important;
  box-shadow: none !important;
}

.sov-ui-button .q-btn__content {
  gap: var(--sov-ui-icon-gap);
  justify-content: flex-start;
}

.sov-ui-button .q-icon {
  width: var(--sov-ui-icon-column);
  min-width: var(--sov-ui-icon-column);
  margin: 0 !important;
  flex: 0 0 var(--sov-ui-icon-column);
  font-size: 20px;
  text-align: center;
}

.sov-ui-button--primary {
  border-color: var(--accent) !important;
  color: #ffffff !important;
  background: var(--accent) !important;
}

.sov-ui-button--secondary {
  border-color: color-mix(in srgb, var(--accent) 34%, var(--border)) !important;
  color: var(--accent) !important;
}

.sov-ui-button--quiet {
  border-color: transparent !important;
  color: var(--dim) !important;
  background: transparent !important;
}

.sov-ui-button--danger {
  border-color: color-mix(in srgb, var(--err) 52%, var(--border)) !important;
  color: var(--err) !important;
  background: color-mix(in srgb, var(--err) 5%, var(--bg-panel)) !important;
}

.sov-ui-button--compact {
  min-height: 34px;
  padding-inline: 10px !important;
}

.sov-ui-button--icon {
  width: var(--sov-ui-hit);
  min-width: var(--sov-ui-hit) !important;
  height: var(--sov-ui-hit);
  padding: 0 !important;
}

.sov-ui-button--icon .q-btn__content {
  gap: 0;
  justify-content: center;
}

.sov-ui-button--icon .q-icon {
  width: auto;
  min-width: 0;
  flex-basis: auto;
}

.sov-ui-button--primary .q-btn__content,
.sov-ui-button--primary .q-icon {
  color: #ffffff !important;
}

.sov-ui-button:hover {
  border-color: color-mix(in srgb, var(--accent) 55%, var(--border)) !important;
  background: color-mix(in srgb, var(--accent) 6%, var(--bg-panel)) !important;
}

.sov-ui-button--primary:hover {
  background: color-mix(in srgb, var(--accent) 90%, #000000) !important;
}

.sov-ui-button--danger:hover {
  border-color: var(--err) !important;
  background: color-mix(in srgb, var(--err) 9%, var(--bg-panel)) !important;
}

.sov-ui-input .q-field__control,
.sov-ui-select .q-field__control {
  min-height: var(--sov-ui-hit);
  color: var(--text);
  background: var(--input-bg);
}

.sov-ui-input .q-field__control::before,
.sov-ui-select .q-field__control::before {
  border-color: var(--border) !important;
}

.sov-ui-input .q-field__control:hover::before,
.sov-ui-input.q-field--focused .q-field__control::before,
.sov-ui-select .q-field__control:hover::before,
.sov-ui-select.q-field--focused .q-field__control::before {
  border-color: var(--accent) !important;
}

.sov-ui-button:active:not(:disabled),
.sov-ui-source-chip:active {
  transform: scale(.96);
}

.sov-ui-shell :focus-visible {
  outline: 2px solid var(--accent) !important;
  outline-offset: 2px !important;
  box-shadow: var(--sov-ui-shadow-focus) !important;
}

.sov-ui-shell .sov-ui-button.q-btn:focus-visible {
  outline: 2px solid var(--accent) !important;
  outline-offset: 2px !important;
  box-shadow: var(--sov-ui-shadow-focus) !important;
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
  gap: 2px;
  padding: 0;
  border-radius: 8px;
  background: transparent;
  box-shadow: none;
}

.sov-nav-switch {
  min-height: var(--sov-ui-hit) !important;
  padding: 0 8px !important;
  border: 1px solid transparent !important;
  border-radius: 7px !important;
  font-family: var(--sov-ui-font-prose) !important;
  font-size: 13px !important;
  font-weight: 700 !important;
  letter-spacing: 0;
  white-space: nowrap;
  color: var(--dim) !important;
  background: transparent !important;
  box-shadow: none;
  transition: background-color .16s ease, box-shadow .16s ease,
    color .16s ease, transform .12s ease, filter .16s ease;
}

.sov-nav-switch--active {
  border-color: color-mix(in srgb, var(--accent) 24%, var(--border)) !important;
  color: var(--accent) !important;
  background: color-mix(in srgb, var(--accent) 10%, var(--bg-panel)) !important;
  box-shadow: inset 3px 0 0 var(--accent);
}

.sov-nav-switch--active .q-btn__content,
.sov-nav-switch--active .q-icon {
  color: var(--accent) !important;
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
  color: var(--text);
  font-size: var(--sov-ui-font-size-control);
  font-weight: 850;
  letter-spacing: 0;
}

.sov-mobile-sections-button {
  display: none !important;
}

.sov-mobile-sections-menu {
  min-width: 210px;
  padding: 6px;
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text);
  background: var(--bg-panel) !important;
  box-shadow: var(--sov-ui-shadow-card);
}

.sov-mobile-sections-menu .q-item {
  min-height: 40px;
  border-radius: 7px;
  font-family: var(--sov-ui-font-prose);
  font-size: var(--sov-ui-font-size-control);
  font-weight: 650;
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

.sov-topbar-icon-action {
  width: 36px;
  min-width: 36px !important;
  height: 36px;
  min-height: 36px !important;
  padding: 0 !important;
}

.sov-topbar-icon-action .q-btn__content {
  gap: 0 !important;
  font-size: 0 !important;
}

.sov-topbar-icon-action .q-icon {
  font-size: 20px;
}

.sov-composer-prompt-head {
  width: 100%;
  margin-bottom: 4px;
  padding-inline: 3px;
  align-items: baseline;
  justify-content: space-between;
}

.sov-composer-prompt-label {
  color: var(--text);
  font-size: 13px;
  font-weight: 800;
}

.sov-composer-key-hint {
  color: var(--dim);
  font-size: 11px;
  font-weight: 500;
}

.sov-app-content .sov-composer-input {
  padding: 10px 12px;
  border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--border)) !important;
  background: var(--bg-panel) !important;
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--accent) 8%, transparent),
    inset 0 1px 2px rgba(20, 52, 34, .035);
}

.sov-app-content .sov-composer-input:focus-within {
  border-color: var(--accent) !important;
  box-shadow: var(--sov-ui-shadow-focus);
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
.sov-source-technical {
  width: 100%;
  margin-top: 8px;
  color: var(--dim);
  font-size: var(--sov-ui-font-size-meta);
}
.sov-source-primary__icon {
  width: var(--sov-ui-icon-column);
  min-width: var(--sov-ui-icon-column);
  margin-right: var(--sov-ui-icon-gap);
  flex: 0 0 var(--sov-ui-icon-column);
  color: var(--accent);
  font-size: 18px;
  text-align: center;
}
.sov-source-primary .q-btn__content {
  width: 100%;
  gap: var(--sov-ui-icon-gap);
  flex-wrap: nowrap;
  justify-content: flex-start;
  text-align: left;
}
.sov-source-primary .q-btn__content > .q-icon {
  width: var(--sov-ui-icon-column);
  min-width: var(--sov-ui-icon-column);
  margin: 0;
  flex: 0 0 var(--sov-ui-icon-column);
  color: var(--accent);
  font-size: 18px;
  text-align: center;
}
.sov-source-technical__ref {
  padding: 4px 0 7px;
  color: var(--dim);
  font-family: var(--sov-ui-font-code);
  font-size: 11px;
  line-height: 1.4;
  overflow-wrap: anywhere;
}
.sov-answer-feedback {
  min-height: 32px;
  margin-left: 4px;
  gap: 4px;
  align-items: center;
}
.sov-answer-feedback__label {
  margin-right: 2px;
  color: var(--dim);
  font-size: var(--sov-ui-font-size-meta);
}
.sov-answer-feedback__button {
  min-height: 30px !important;
  padding: 2px 8px !important;
  color: var(--dim) !important;
  border: 1px solid transparent !important;
  border-radius: var(--sov-ui-radius-control) !important;
  font-size: var(--sov-ui-font-size-meta) !important;
}
.sov-answer-feedback__button:hover {
  color: var(--text) !important;
  background: color-mix(in srgb, var(--accent) 6%, transparent) !important;
}
.sov-answer-feedback__button--active {
  font-weight: 800 !important;
}
.sov-answer-feedback__button--good {
  color: var(--ok) !important;
  border-color: color-mix(in srgb, var(--ok) 38%, var(--border)) !important;
  background: color-mix(in srgb, var(--ok) 8%, var(--card-bg)) !important;
}
.sov-answer-feedback__button--bad {
  color: var(--err) !important;
  border-color: color-mix(in srgb, var(--err) 38%, var(--border)) !important;
  background: color-mix(in srgb, var(--err) 7%, var(--card-bg)) !important;
}
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
.sov-mail-page,
.sov-mail-settings-page,
.sov-tools-page {
  width: min(100%, 1220px);
  min-width: 0;
  margin: 0 auto;
  padding: 18px;
  gap: 12px !important;
  overflow-x: clip;
}

.sov-mail-hero,
.sov-mail-settings-hero,
.sov-tools-hero {
  width: 100%;
  min-width: 0;
  padding: 16px 18px;
  background:
    linear-gradient(
      120deg,
      color-mix(in srgb, var(--accent) 7%, var(--card-bg)),
      var(--card-bg) 58%
    );
}

.sov-mail-hero__detail,
.sov-mail-settings-subtitle,
.sov-tools-summary,
.sov-tools-detail {
  color: var(--dim);
  font-size: var(--sov-ui-font-size-meta);
  line-height: 1.45;
  text-wrap: pretty;
}

.sov-mail-status-strip {
  display: flex;
  width: 100%;
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

.sov-mail-search {
  width: 100%;
  min-width: 0;
  gap: 8px;
  align-items: center;
  flex-wrap: nowrap;
}

.sov-mail-search__field {
  min-width: 0;
  flex: 1;
}

.sov-mail-workbench {
  display: grid;
  width: 100%;
  min-width: 0;
  min-height: 520px;
  grid-template-columns: minmax(210px, .72fr) minmax(280px, .95fr) minmax(360px, 1.7fr);
  gap: 10px;
}

.sov-mail-column {
  min-width: 0;
  min-height: 0;
  max-height: calc(100vh - 245px);
  padding: 12px;
  overflow: auto;
}

.sov-mail-column__content {
  min-width: 0;
  gap: 8px !important;
}

.sov-mail-account,
.sov-mail-message {
  display: flex;
  width: 100%;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: var(--sov-ui-radius-control);
  color: var(--text);
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.sov-mail-account {
  gap: var(--sov-ui-icon-gap);
  align-items: flex-start;
}

.sov-mail-account:hover,
.sov-mail-message:hover {
  border-color: color-mix(in srgb, var(--accent) 52%, var(--border));
  background: color-mix(in srgb, var(--accent) 5%, var(--card-bg));
}

.sov-mail-account--active {
  border-color: color-mix(in srgb, var(--accent) 72%, var(--border));
  background: color-mix(in srgb, var(--accent) 9%, var(--card-bg));
  box-shadow: inset 3px 0 0 var(--accent);
}

.sov-mail-account__icon,
.sov-mail-account-card__icon,
.sov-mail-collector-card__icon {
  width: var(--sov-ui-icon-column);
  flex: 0 0 var(--sov-ui-icon-column);
  color: var(--accent);
  font-size: 20px;
}

.sov-mail-account__copy,
.sov-mail-account-card__copy,
.sov-mail-collector-card__copy {
  min-width: 0;
  flex: 1;
  gap: 2px !important;
}

.sov-mail-account__title,
.sov-mail-message__subject,
.sov-mail-detail__title,
.sov-mail-settings-card-title {
  color: var(--text);
  font-weight: 800;
  line-height: 1.3;
  text-wrap: pretty;
}

.sov-mail-account__title,
.sov-mail-message__subject,
.sov-mail-settings-card-title {
  font-size: var(--sov-ui-font-size-control);
}

.sov-mail-account__dataset,
.sov-mail-account__meta,
.sov-mail-message__sender,
.sov-mail-message__date,
.sov-mail-detail__meta,
.sov-mail-meta,
.sov-mail-settings-note {
  color: var(--dim);
  font-size: var(--sov-ui-font-size-meta);
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.sov-mail-message {
  gap: 3px;
  align-items: stretch;
  flex-direction: column;
}

.sov-mail-message__head {
  width: 100%;
  min-width: 0;
  gap: 8px;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: nowrap;
}

.sov-mail-message__subject {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sov-mail-detail__head {
  min-width: 0;
  gap: 4px !important;
}

.sov-mail-detail__title {
  font-size: 17px;
}

.sov-mail-detail__participant {
  color: var(--text);
  font-size: var(--sov-ui-font-size-control);
  font-weight: 650;
  overflow-wrap: anywhere;
}

.sov-mail-detail__actions,
.sov-mail-attachments,
.sov-mail-search {
  flex-wrap: wrap;
}

.sov-mail-detail__actions {
  width: 100%;
  gap: 8px;
}

.sov-mail-body {
  width: 100%;
  min-height: 180px;
  padding: 14px;
}

.sov-mail-body__text {
  color: var(--text);
  font-size: var(--sov-ui-font-size-body);
  line-height: 1.58;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.sov-mail-attachment {
  width: 100%;
  min-width: 0;
  padding: 7px 9px;
  gap: var(--sov-ui-icon-gap);
  align-items: center;
  border: 1px solid var(--border);
  border-radius: var(--sov-ui-radius-control);
}

.sov-mail-attachment__name {
  min-width: 0;
  flex: 1;
  color: var(--text);
  font-size: var(--sov-ui-font-size-control);
  font-weight: 700;
  overflow-wrap: anywhere;
}

.sov-mail-disclosure,
.sov-tools-disclosure {
  color: var(--text);
  font-size: var(--sov-ui-font-size-control);
}

.sov-mail-settings-head,
.sov-mail-account-card__row,
.sov-tools-hero__row,
.sov-tools-section__head {
  width: 100%;
  min-width: 0;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: nowrap;
}

.sov-mail-settings-identity {
  min-width: 0;
  max-width: 760px;
  flex: 1;
  gap: 5px !important;
}

.sov-mail-settings-section,
.sov-tools-section {
  width: 100%;
  min-width: 0;
  padding: 16px;
}

.sov-mail-collector-card,
.sov-mail-account-card {
  display: flex;
  width: 100%;
  min-width: 0;
  margin-top: 12px;
  padding: 13px;
  gap: var(--sov-ui-icon-gap);
  align-items: flex-start;
  border: 1px solid var(--border);
  border-radius: var(--sov-ui-radius-panel);
  background: color-mix(in srgb, var(--bg) 76%, var(--card-bg));
}

.sov-mail-account-card__identity {
  width: 100%;
  min-width: 0;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.sov-mail-account-card__actions,
.sov-tools-actions,
.sov-tools-prompt__actions {
  gap: 6px;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
}

.sov-mail-settings-dataset {
  color: var(--text);
  font-size: var(--sov-ui-font-size-control);
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}

.sov-mail-settings-loading {
  margin-top: 14px;
  color: var(--dim);
  font-size: var(--sov-ui-font-size-control);
}

.sov-mail-settings-dialog {
  width: min(520px, calc(100vw - 32px));
}

.sov-mail-settings-dialog-title {
  color: var(--text);
  font-size: 17px;
  font-weight: 850;
  text-wrap: balance;
}

/* Tools: a single operator hierarchy. Prompt editing is a secondary disclosure. */
.sov-tools-page {
  max-width: 1160px;
}

.sov-tools-hero__row .sov-ui-section-heading,
.sov-tools-section__head .sov-ui-section-heading {
  min-width: 0;
  flex: 1;
}

.sov-tools-section {
  gap: 12px;
}

.sov-tools-summary {
  margin-top: 2px;
}

.sov-tools-fgis {
  width: 100%;
  padding: 12px;
}

.sov-tools-fgis__head {
  width: 100%;
  min-width: 0;
  gap: var(--sov-ui-icon-gap);
  align-items: center;
  flex-wrap: nowrap;
}

.sov-tools-state-icon {
  width: var(--sov-ui-icon-column);
  flex: 0 0 var(--sov-ui-icon-column);
  font-size: 20px;
}

.sov-tools-state-icon--accent { color: var(--accent); }
.sov-tools-state-icon--ok { color: var(--ok); }
.sov-tools-state-icon--error { color: var(--err); }
.sov-tools-state-icon--muted { color: var(--dim); }

.sov-tools-fgis__title {
  min-width: 0;
  flex: 1;
  color: var(--text);
  font-size: var(--sov-ui-font-size-control);
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}

.sov-tools-metrics {
  width: 100%;
  gap: 6px;
  flex-wrap: wrap;
}

.sov-tools-log {
  height: 180px;
  padding: 9px;
  border: 1px solid var(--border);
  border-radius: var(--sov-ui-radius-control);
  color: var(--text);
  background: var(--bg);
  font-family: var(--sov-ui-font-code);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.sov-tools-source-list,
.sov-tools-prompt-list {
  gap: 8px !important;
}

.sov-tools-source {
  width: 100%;
  min-width: 0;
  padding: 12px;
}

.sov-tools-source__row {
  width: 100%;
  min-width: 0;
  gap: var(--sov-ui-icon-gap);
  align-items: flex-start;
  flex-wrap: nowrap;
}

.sov-tools-source__icon {
  width: var(--sov-ui-icon-column);
  flex: 0 0 var(--sov-ui-icon-column);
  color: var(--accent);
  font-size: 20px;
}

.sov-tools-source__copy,
.sov-tools-required-doc__copy {
  min-width: 0;
  flex: 1;
  gap: 3px !important;
}

.sov-tools-source__identity {
  width: 100%;
  min-width: 0;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.sov-tools-source__title,
.sov-tools-required-doc__title {
  color: var(--text);
  font-size: var(--sov-ui-font-size-body);
  font-weight: 800;
  line-height: 1.3;
  text-wrap: pretty;
}

.sov-tools-source__domain,
.sov-tools-source__meta,
.sov-tools-layer__detail,
.sov-tools-prompt__runtime {
  color: var(--dim);
  font-size: var(--sov-ui-font-size-meta);
  line-height: 1.42;
  overflow-wrap: anywhere;
}

.sov-tools-source__line {
  color: var(--text);
  font-size: var(--sov-ui-font-size-control);
  line-height: 1.42;
  overflow-wrap: anywhere;
}

.sov-tools-source__meta--strong {
  font-weight: 750;
}

.sov-tools-source__actions {
  flex: 0 0 auto;
  gap: 4px;
  align-items: center;
}

.sov-tools-required-doc {
  width: 100%;
  padding: 9px 0;
  border-top: 1px solid var(--border);
}

.sov-tools-required-doc__row {
  width: 100%;
  min-width: 0;
  gap: 10px;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: nowrap;
}

.sov-tools-layer {
  width: 100%;
  min-width: 0;
  padding: 6px 8px;
  gap: var(--sov-ui-icon-gap);
  align-items: center;
  border: 1px solid var(--border);
  border-radius: var(--sov-ui-radius-control);
  flex-wrap: nowrap;
}

.sov-tools-layer__icon {
  width: var(--sov-ui-icon-column);
  flex: 0 0 var(--sov-ui-icon-column);
  font-size: 17px;
}

.sov-tools-layer__title {
  min-width: 0;
  flex: 1;
  color: var(--text);
  font-size: var(--sov-ui-font-size-control);
  font-weight: 750;
}

.sov-tools-layer__state {
  flex: 0 0 auto;
  font-size: var(--sov-ui-font-size-meta);
  font-weight: 800;
}

.sov-tools-layer--ok .sov-tools-layer__icon,
.sov-tools-layer--ok .sov-tools-layer__state { color: var(--ok); }
.sov-tools-layer--accent .sov-tools-layer__icon,
.sov-tools-layer--accent .sov-tools-layer__state { color: var(--accent); }
.sov-tools-layer--warn .sov-tools-layer__icon,
.sov-tools-layer--warn .sov-tools-layer__state { color: var(--warn); }
.sov-tools-layer--error .sov-tools-layer__icon,
.sov-tools-layer--error .sov-tools-layer__state { color: var(--err); }
.sov-tools-layer--muted .sov-tools-layer__icon,
.sov-tools-layer--muted .sov-tools-layer__state { color: var(--dim); }

.sov-tools-prompt {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: var(--sov-ui-radius-control);
  color: var(--text);
  background: color-mix(in srgb, var(--bg) 80%, transparent);
}

.sov-tools-prompt__meta {
  width: 100%;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.sov-tools-prompt__editor {
  margin-top: 8px;
  gap: 8px !important;
}

.sov-tools-prompt .sov-prompt-textarea textarea {
  color: var(--text);
  font-family: var(--sov-ui-font);
  font-size: var(--sov-ui-font-size-control);
  line-height: 1.5;
}

/* Checklist review: dense engineering workbench, not a dashboard.
   Existing surfaces and controls carry the hierarchy; accent is reserved for
   the one primary action and semantic states. */
.sov-checklist {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--sov-ui-space-4);
}

.sov-checklist__head,
.sov-checklist__run,
.sov-checklist__reports,
.sov-checklist-dialog__actions {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  gap: var(--sov-ui-space-2);
}

.sov-checklist__head {
  align-items: flex-start;
  justify-content: space-between;
}

.sov-checklist__setup {
  display: grid;
  width: 100%;
  min-width: 0;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--sov-ui-space-3);
}

.sov-checklist__field,
.sov-checklist-dialog__input {
  width: 100%;
  min-width: 0;
}

.sov-checklist__run {
  flex-wrap: wrap;
}

.sov-checklist__status,
.sov-checklist__reports-label,
.sov-checklist-dialog__meta,
.sov-checklist-dialog__note {
  color: var(--dim);
  font-size: var(--sov-ui-font-size-meta);
  line-height: 1.45;
}

.sov-checklist__summary {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  gap: var(--sov-ui-space-2);
  flex-wrap: wrap;
}

.sov-checklist__reports {
  flex-wrap: wrap;
}

.sov-checklist__table {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  border: var(--sov-ui-border);
  border-radius: var(--sov-ui-radius-control);
}

.sov-checklist__table .q-table th {
  color: var(--dim);
  font-size: var(--sov-ui-font-size-meta);
  font-weight: 700;
}

.sov-checklist__table .q-table td {
  color: var(--text);
  font-size: var(--sov-ui-font-size-control);
  vertical-align: top;
}

.sov-checklist__table .q-table tbody tr {
  cursor: pointer;
}

.sov-checklist__table .q-table tbody tr:focus-within,
.sov-checklist__table .q-table tbody tr:hover {
  background: color-mix(in srgb, var(--accent) 6%, var(--card-bg));
}

.sov-checklist-dialog {
  width: min(720px, calc(100vw - 32px));
  max-height: min(86vh, 820px);
  overflow-y: auto;
  gap: var(--sov-ui-space-3) !important;
}

.sov-checklist-dialog__title {
  color: var(--text);
  font-size: 16px;
  font-weight: 750;
  line-height: 1.35;
  text-wrap: balance;
}

.sov-checklist-dialog__evidence {
  width: 100%;
  min-width: 0;
  gap: var(--sov-ui-space-2) !important;
}

.sov-checklist-dialog__source {
  width: 100%;
  padding: var(--sov-ui-space-2) var(--sov-ui-space-3);
  overflow-wrap: anywhere;
  border: var(--sov-ui-border);
  border-radius: var(--sov-ui-radius-control);
  background: var(--bg-mod);
  color: var(--text);
  font-size: var(--sov-ui-font-size-meta);
  line-height: 1.5;
}

.sov-checklist-dialog__details {
  width: 100%;
  color: var(--text);
}

.sov-checklist-dialog__actions {
  justify-content: flex-end;
  flex-wrap: wrap;
}

/* Configuration home: one readiness passport, then readable working contours.
   Secondary and risky tools stay in disclosures instead of competing with status. */
.sov-config-page {
  width: min(100%, 1120px);
  min-width: 0;
  margin: 0 auto;
  padding: 20px;
  gap: 12px !important;
}

.sov-config-hero {
  width: 100%;
  max-width: 100%;
  padding: 18px;
  background:
    linear-gradient(
      120deg,
      color-mix(in srgb, var(--accent) 7%, var(--card-bg)),
      var(--card-bg) 52%
    );
  overflow: hidden;
}

.sov-config-hero__row,
.sov-config-disclosure__header {
  width: 100%;
  min-width: 0;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: nowrap;
}

.sov-config-hero__identity {
  width: 100%;
  min-width: 0;
  max-width: 720px;
  gap: 5px !important;
}

.sov-config-hero .sov-acronym-identity {
  max-width: 100%;
}

.sov-config-eyebrow {
  color: var(--dim);
  font-size: 11px;
  font-weight: 750;
  line-height: 1.2;
  letter-spacing: .08em;
  text-transform: uppercase;
}

.sov-config-intro,
.sov-config-last-run,
.sov-config-disclosure__intro {
  color: var(--dim);
  font-size: var(--sov-ui-font-size-meta);
  font-weight: 400;
  line-height: 1.45;
}

.sov-config-last-run {
  margin-top: 2px;
  font-variant-numeric: tabular-nums;
}

.sov-config-hero__actions,
.sov-config-disclosure__actions {
  flex: 0 0 auto;
  gap: 8px;
  align-items: center;
  flex-wrap: nowrap;
}

.sov-config-status-strip {
  display: grid;
  width: 100%;
  min-width: 0;
  margin-top: 16px;
  grid-template-columns: minmax(260px, 1fr) minmax(360px, auto);
  border: 1px solid color-mix(in srgb, var(--border) 86%, transparent);
  border-radius: var(--sov-ui-radius-card);
  background: color-mix(in srgb, var(--bg) 72%, transparent);
  overflow: hidden;
}

.sov-config-status-strip__overall {
  min-width: 0;
}

.sov-config-readiness {
  --sov-config-tone: var(--dim);
  display: flex;
  min-height: 76px;
  padding: 12px 14px;
  gap: 10px;
  align-items: center;
}

.sov-config-readiness--ok { --sov-config-tone: var(--ok); }
.sov-config-readiness--warn { --sov-config-tone: var(--warn); }
.sov-config-readiness--err { --sov-config-tone: var(--err); }

.sov-config-readiness__mark {
  display: inline-grid;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  place-items: center;
  color: var(--sov-config-tone);
  border: 1px solid color-mix(in srgb, var(--sov-config-tone) 45%, var(--border));
  border-radius: 50%;
  background: color-mix(in srgb, var(--sov-config-tone) 8%, var(--card-bg));
  font-size: 17px;
  font-weight: 800;
}

.sov-config-readiness__copy {
  min-width: 0;
}

.sov-config-readiness__title {
  color: var(--text);
  font-size: 14px;
  font-weight: 760;
  line-height: 1.3;
}

.sov-config-readiness__detail {
  margin-top: 2px;
  color: var(--dim);
  font-size: var(--sov-ui-font-size-meta);
  line-height: 1.4;
}

.sov-config-status-strip__metrics {
  display: grid;
  min-width: 360px;
  grid-template-columns: repeat(4, minmax(82px, 1fr));
  border-left: 1px solid var(--border);
}

.sov-config-metric {
  display: flex;
  min-width: 0;
  padding: 11px 10px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  border-left: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
  text-align: center;
}

.sov-config-metric:first-child {
  border-left: 0;
}

.sov-config-metric__value {
  color: var(--text);
  font-family: var(--sov-ui-font-code);
  font-size: 18px;
  font-weight: 780;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.sov-config-metric__label {
  margin-top: 3px;
  color: var(--dim);
  font-size: 11px;
  line-height: 1.2;
}

.sov-config-metric--ok .sov-config-metric__value { color: var(--ok); }
.sov-config-metric--warn .sov-config-metric__value { color: var(--warn); }
.sov-config-metric--error .sov-config-metric__value { color: var(--err); }

.sov-config-section {
  padding: 16px;
  box-shadow: var(--sov-ui-shadow-card);
}

.sov-config-contours {
  display: grid;
  width: 100%;
  min-width: 0;
  margin-top: 14px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.sov-config-contour {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: var(--sov-ui-radius-card);
  background: color-mix(in srgb, var(--bg) 48%, var(--card-bg));
  overflow: hidden;
}

.sov-config-contour__title {
  margin: 0;
  padding: 10px 12px;
  color: var(--text);
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg-mod) 68%, transparent);
  font-size: 12px;
  font-weight: 760;
  line-height: 1.25;
}

.sov-config-contour__body {
  display: grid;
}

.sov-config-service {
  --sov-config-tone: var(--dim);
  display: grid;
  min-width: 0;
  min-height: 54px;
  padding: 9px 11px;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  gap: 9px;
  align-items: center;
  border-top: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
}

.sov-config-service:first-child { border-top: 0; }
.sov-config-service--ok { --sov-config-tone: var(--ok); }
.sov-config-service--warn { --sov-config-tone: var(--warn); }
.sov-config-service--err { --sov-config-tone: var(--err); }

.sov-config-service__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--sov-config-tone);
}

.sov-config-service__copy { min-width: 0; }

.sov-config-service__name {
  overflow: hidden;
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sov-config-service__detail {
  margin-top: 2px;
  overflow: hidden;
  color: var(--dim);
  font-size: 11px;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sov-config-service__status {
  padding: 3px 6px;
  color: var(--sov-config-tone);
  border: 1px solid color-mix(in srgb, var(--sov-config-tone) 42%, var(--border));
  border-radius: 4px;
  background: color-mix(in srgb, var(--sov-config-tone) 6%, var(--card-bg));
  font-size: 10px;
  font-weight: 720;
  line-height: 1.2;
  white-space: nowrap;
}

.sov-config-disclosure {
  min-width: 0;
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--sov-ui-radius-card);
  background: var(--card-bg);
  box-shadow: var(--sov-ui-shadow-card);
  overflow: hidden;
}

.sov-config-disclosure > .q-expansion-item__container > .q-item {
  min-height: 46px;
  padding: 8px 12px;
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
}

.sov-config-disclosure > .q-expansion-item__container > .q-expansion-item__content {
  padding: 0 12px 12px;
}

.sov-config-disclosure__header {
  margin-bottom: 10px;
  align-items: center;
}

.sov-config-checks,
.sov-config-backups {
  width: 100%;
  min-width: 0;
  margin-top: 10px;
  gap: 8px !important;
}

.sov-config-check {
  --sov-config-tone: var(--dim);
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-left: 3px solid var(--sov-config-tone);
  border-radius: 6px;
  background: color-mix(in srgb, var(--bg) 42%, var(--card-bg));
}

.sov-config-check--ok { --sov-config-tone: var(--ok); }
.sov-config-check--warn { --sov-config-tone: var(--warn); }
.sov-config-check--err { --sov-config-tone: var(--err); }

.sov-config-check__header,
.sov-config-check__values {
  width: 100%;
  min-width: 0;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  flex-wrap: nowrap;
}

.sov-config-check__name {
  min-width: 0;
  color: var(--text);
  font-size: 13px;
  font-weight: 720;
}

.sov-config-check__status {
  flex: 0 0 auto;
  color: var(--sov-config-tone);
  font-size: 11px;
  font-weight: 720;
}

.sov-config-check__values { margin-top: 4px; }

.sov-config-check__value {
  min-width: 0;
  color: var(--sov-config-tone);
  font-family: var(--sov-ui-font-code);
  font-size: 13px;
  font-weight: 720;
}

.sov-config-check__expected,
.sov-config-check__message,
.sov-config-check__latency {
  color: var(--dim);
  font-size: 11px;
  line-height: 1.35;
}

.sov-config-check__expected { flex: 0 0 auto; }
.sov-config-check__message { margin-top: 4px; }
.sov-config-check__latency {
  margin-top: 4px;
  font-family: var(--sov-ui-font-code);
  font-variant-numeric: tabular-nums;
}

.sov-config-log {
  height: 190px;
  margin-top: 10px;
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
  background: color-mix(in srgb, var(--bg) 88%, var(--card-bg));
  font-family: var(--sov-ui-font-code);
  font-size: 11px;
}

.sov-config-page .diag-acronym-grid {
  margin-top: 10px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.sov-config-page .diag-acronym-item {
  min-height: 0;
  padding: 10px;
  border-color: var(--border);
  background: color-mix(in srgb, var(--bg) 44%, var(--card-bg));
  box-shadow: none;
}

.sov-config-page .diag-acronym-code {
  color: var(--accent);
  font-family: var(--sov-ui-font-prose);
  font-size: 12px;
  font-weight: 760;
}

.sov-config-page .diag-acronym-full {
  color: var(--text);
  font-family: var(--sov-ui-font-prose);
  font-size: 11px;
}

.sov-config-page .diag-acronym-role {
  color: var(--dim);
  font-family: var(--sov-ui-font-prose);
  font-size: 11px;
}

.sov-flex-spacer {
  min-width: 0;
  flex: 1 1 auto;
}

.sov-datasets-page {
  box-sizing: border-box;
  width: min(1120px, 100%);
  min-width: 0;
  margin: 0 auto;
  padding: 16px 18px 28px;
  gap: 12px !important;
}

.sov-datasets-page > .sov-ui-panel,
.sov-datasets-page > .sov-dataset-disclosure {
  width: 100%;
  max-width: 100%;
}

.sov-datasets-hero {
  padding: 14px 16px;
}

.sov-datasets-hero__row {
  min-width: 0;
  gap: 12px;
  flex-wrap: nowrap;
}

.sov-datasets-hero__detail {
  max-width: 720px;
  margin-top: 8px;
  color: var(--dim);
  font-size: 12px;
  line-height: 1.45;
  text-wrap: pretty;
}

.sov-dataset-add {
  flex: 0 0 auto;
}

.sov-dataset-summary {
  display: grid;
  grid-template-columns: minmax(180px, .75fr) minmax(0, 2.25fr);
  align-items: stretch;
  padding: 0;
  overflow: hidden;
}

.sov-dataset-summary__copy {
  min-width: 0;
  padding: 12px 14px;
}

.sov-dataset-summary__title {
  color: var(--text);
  font-size: 13px;
  font-weight: 750;
}

.sov-dataset-summary__detail {
  margin-top: 2px;
  color: var(--dim);
  font-size: 11px;
  line-height: 1.35;
}

.sov-dataset-summary__metrics {
  display: grid;
  min-width: 0;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  border-left: 1px solid var(--border);
}

.sov-dataset-summary__metric {
  min-width: 0;
  padding: 10px 9px;
  text-align: left;
}

.sov-dataset-summary__metric + .sov-dataset-summary__metric {
  border-left: 1px solid var(--border);
}

.sov-dataset-summary__value {
  color: var(--text);
  font-family: var(--sov-ui-font-prose);
  font-size: 17px;
  font-weight: 760;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
}

.sov-dataset-summary__label {
  margin-top: 2px;
  color: var(--dim);
  font-size: 10.5px;
  line-height: 1.2;
  white-space: nowrap;
}

.sov-dataset-registry-panel {
  padding: 14px;
}

.sov-dataset-section-head {
  min-width: 0;
  gap: 12px;
  flex-wrap: nowrap;
}

.sov-dataset-toolbar {
  display: grid;
  min-width: 0;
  grid-template-columns: minmax(230px, 1fr) auto;
  gap: 10px;
  align-items: center;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.sov-dataset-search {
  width: 100%;
  min-width: 0;
}

.sov-dataset-search .q-field__control {
  min-height: 40px;
}

.sov-dataset-filters {
  min-width: 0;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--border);
  border-radius: var(--sov-ui-radius-control);
  background: var(--bg-mod);
  flex-wrap: nowrap;
}

.sov-dataset-filter {
  min-width: auto !important;
}

.sov-dataset-filter--active {
  color: var(--accent) !important;
  background: color-mix(in srgb, var(--accent) 10%, var(--card-bg)) !important;
}

.sov-dataset-results {
  min-width: 0;
  margin-top: 12px;
}

.sov-dataset-registry {
  min-width: 0;
  gap: 8px !important;
}

.sov-dataset-row {
  display: grid;
  width: 100%;
  min-width: 0;
  grid-template-columns: minmax(240px, 1fr) minmax(300px, 1.4fr) auto;
  grid-template-areas:
    "head facts actions"
    "progress progress actions"
    "note note actions";
  column-gap: 16px;
  row-gap: 8px;
  align-items: center;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--sov-ui-radius-card);
  background: var(--card-bg);
  box-shadow: 0 1px 2px rgba(20, 52, 34, .025);
}

.sov-dataset-row:hover {
  border-color: color-mix(in srgb, var(--accent) 26%, var(--border));
  background: color-mix(in srgb, var(--accent) 2.5%, var(--card-bg));
}

.sov-dataset-row__head {
  grid-area: head;
  min-width: 0;
  gap: 10px;
  flex-wrap: nowrap;
}

.sov-dataset-row__identity {
  display: grid;
  min-width: 0;
  grid-template-columns: var(--sov-ui-icon-column) minmax(0, 1fr);
  gap: var(--sov-ui-icon-gap);
  align-items: center;
  flex: 1 1 auto;
}

.sov-dataset-row__state-icon {
  width: var(--sov-ui-icon-column);
  min-width: var(--sov-ui-icon-column);
  font-size: 18px;
  text-align: center;
}

.sov-dataset-row__copy {
  min-width: 0;
  gap: 1px !important;
}

.sov-dataset-row__name {
  min-width: 0;
  overflow: hidden;
  color: var(--text);
  font-size: 13px;
  font-weight: 760;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sov-dataset-row__scope,
.sov-dataset-row__note {
  color: var(--dim);
  font-size: 11px;
  line-height: 1.35;
}

.sov-dataset-row__facts {
  display: grid;
  min-width: 0;
  grid-area: facts;
  grid-template-columns: repeat(5, minmax(54px, 1fr));
  gap: 6px;
}

.sov-dataset-fact {
  min-width: 0;
}

.sov-dataset-fact__label {
  color: var(--dim);
  font-size: 10px;
  line-height: 1.2;
  white-space: nowrap;
}

.sov-dataset-fact__value {
  margin-top: 1px;
  color: var(--text);
  font-size: 13px;
  font-weight: 720;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.sov-dataset-row__progress {
  grid-area: progress;
  min-width: 0;
}

.sov-dataset-progress {
  display: flex;
  width: 100%;
  min-width: 120px;
  height: 5px;
  overflow: hidden;
  border-radius: 3px;
  background: var(--bg-mod);
}

.sov-dataset-row__note {
  grid-area: note;
}

.sov-dataset-row__actions {
  grid-area: actions;
  width: auto;
  min-width: 0;
  gap: 6px;
  flex-wrap: nowrap;
  justify-content: flex-end;
}

.sov-dataset-more {
  flex: 0 0 auto;
}

.sov-dataset-actions-menu {
  min-width: 220px;
}

.sov-dataset-menu-danger {
  color: var(--err);
}

.sov-dataset-disclosure,
.sov-dataset-settings {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--sov-ui-radius-card);
  background: var(--card-bg);
}

.sov-dataset-disclosure > .q-expansion-item__container > .q-item,
.sov-dataset-settings > .q-expansion-item__container > .q-item {
  min-height: 42px;
  padding: 8px 12px;
  color: var(--text);
  font-size: 13px;
  font-weight: 720;
}

.sov-dataset-disclosure > .q-expansion-item__container > .q-expansion-item__content {
  padding: 0 12px 12px;
}

.sov-dataset-disclosure__intro,
.sov-dataset-settings__note {
  color: var(--dim);
  font-size: 11.5px;
  line-height: 1.45;
}

.sov-dataset-operator {
  margin-top: 10px;
}

.sov-dataset-operator-summary {
  width: 100%;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--bg-mod);
}

.sov-dataset-operator-line,
.sov-dataset-index-controls,
.sov-dataset-settings__switches {
  min-width: 0;
  gap: 10px;
  flex-wrap: wrap;
}

.sov-dataset-operator-icon {
  width: var(--sov-ui-icon-column);
  min-width: var(--sov-ui-icon-column);
  color: var(--accent);
  font-size: 18px;
}

.sov-dataset-operator-title {
  color: var(--text);
  font-size: 12.5px;
  font-weight: 740;
}

.sov-dataset-operator-fact,
.sov-dataset-operator-memory,
.sov-dataset-index-status {
  color: var(--dim);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.sov-dataset-operator-note {
  margin-top: 6px;
  color: var(--dim);
  font-size: 11.5px;
  line-height: 1.4;
}

.sov-dataset-operator-note--warn {
  color: var(--warn);
}

.sov-dataset-operator-notice {
  margin-top: 8px;
  font-size: 11.5px;
  font-weight: 720;
}

.sov-dataset-operator-notice--ready { color: var(--ok); }
.sov-dataset-operator-notice--error { color: var(--err); }

.sov-dataset-active-job {
  gap: 4px !important;
  margin-top: 10px;
}

.sov-dataset-active-job__head {
  min-width: 0;
  gap: 8px;
  flex-wrap: wrap;
}

.sov-dataset-active-job__title {
  min-width: 160px;
  flex: 1 1 auto;
  color: var(--text);
  font-size: 12px;
  font-weight: 720;
}

.sov-dataset-active-job__id,
.sov-dataset-active-job__meta,
.sov-dataset-active-job__status {
  color: var(--dim);
  font-size: 10.5px;
}

.sov-dataset-active-job__id {
  font-family: var(--sov-ui-font-code);
}

.sov-dataset-active-job__progress {
  height: 5px;
  border-radius: 3px;
}

.sov-dataset-index-controls {
  margin: 10px 0;
}

.sov-dataset-settings {
  margin-top: 8px;
  box-shadow: none;
}

.sov-dataset-settings > .q-expansion-item__container > .q-expansion-item__content {
  padding: 0 12px 12px;
}

.sov-dataset-settings__grid {
  display: grid;
  min-width: 0;
  grid-template-columns: repeat(3, minmax(145px, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.sov-dataset-settings__switches {
  margin-top: 8px;
}

/* History: one readable list, no nested interactive cards. */
.sov-history-page,
.sov-access-page {
  box-sizing: border-box;
  width: min(100%, 1120px);
  min-width: 0;
  margin: 0 auto;
  padding: 18px;
  gap: 12px !important;
  overflow-x: clip;
}

.sov-history-hero,
.sov-access-hero {
  width: 100%;
  min-width: 0;
  padding: 16px 18px;
  background: color-mix(in srgb, var(--accent) 5%, var(--card-bg));
}

.sov-history-hero__row,
.sov-history-list-head,
.sov-access-hero__row,
.sov-access-registry__head {
  width: 100%;
  min-width: 0;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: nowrap;
}

.sov-history-hero__row .sov-ui-section-heading,
.sov-history-list-head .sov-ui-section-heading,
.sov-access-registry__head .sov-ui-section-heading {
  min-width: 0;
  flex: 1;
}

.sov-history-list-panel,
.sov-access-create,
.sov-access-registry {
  width: 100%;
  min-width: 0;
  padding: 16px;
}

.sov-history-list,
.sov-access-key-list {
  width: 100%;
  min-width: 0;
  margin-top: 12px;
  gap: 8px !important;
}

.sov-history-row {
  display: flex;
  width: 100%;
  min-width: 0;
  padding: 12px 14px;
  gap: 16px;
  align-items: center;
}

.sov-history-row__copy {
  min-width: 0;
  flex: 1;
  gap: 4px !important;
}

.sov-history-row__title {
  display: -webkit-box;
  overflow: hidden;
  color: var(--text);
  font-size: var(--sov-ui-font-size-control);
  font-weight: 750;
  line-height: 1.35;
  text-wrap: pretty;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.sov-history-row__meta,
.sov-access-key-row__meta {
  min-width: 0;
  gap: 10px;
  color: var(--dim);
  font-size: var(--sov-ui-font-size-meta);
  line-height: 1.35;
  font-variant-numeric: tabular-nums;
  flex-wrap: wrap;
}

.sov-history-row__open {
  flex: 0 0 auto;
}

/* Access: creation is primary, destructive key actions remain secondary. */
.sov-access-hero__copy {
  min-width: 0;
  max-width: 760px;
  flex: 1;
  gap: 6px !important;
}

.sov-access-intro {
  color: var(--dim);
  font-size: var(--sov-ui-font-size-meta);
  line-height: 1.45;
  text-wrap: pretty;
}

.sov-access-form {
  display: grid;
  width: 100%;
  min-width: 0;
  margin-top: 14px;
  grid-template-columns: minmax(240px, 1.5fr) minmax(180px, 1fr) minmax(150px, .7fr) minmax(150px, .7fr);
  gap: 10px;
  align-items: start;
}

.sov-access-form > * {
  min-width: 0;
  width: 100%;
}

.sov-access-form__actions {
  width: 100%;
  margin-top: 10px;
  gap: 8px;
  justify-content: flex-end;
  flex-wrap: wrap;
}

.sov-access-key-row {
  display: flex;
  width: 100%;
  min-width: 0;
  padding: 12px;
  gap: 14px;
  align-items: center;
}

.sov-access-key-row__main {
  min-width: 0;
  flex: 1;
  gap: var(--sov-ui-icon-gap);
  align-items: flex-start;
  flex-wrap: nowrap;
}

.sov-access-key-row__icon {
  width: var(--sov-ui-icon-column);
  flex: 0 0 var(--sov-ui-icon-column);
  color: var(--accent);
  font-size: 20px;
}

.sov-access-key-row__copy {
  min-width: 0;
  flex: 1;
  gap: 3px !important;
}

.sov-access-key-row__identity {
  width: 100%;
  min-width: 0;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.sov-access-key-row__holder {
  min-width: 0;
  color: var(--text);
  font-size: var(--sov-ui-font-size-control);
  font-weight: 780;
  overflow-wrap: anywhere;
}

.sov-access-key-row__key {
  color: var(--text);
  font-family: var(--sov-ui-font-code);
  font-size: var(--sov-ui-font-size-meta);
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}

.sov-access-key-row__actions {
  flex: 0 0 auto;
  gap: 6px;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
}

.sov-access-key-row__protected {
  flex: 0 0 auto;
  color: var(--ok);
  font-size: var(--sov-ui-font-size-meta);
  font-weight: 750;
}

/* Visual: the embedded map remains the focal working surface. */
.sov-visual-page {
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  padding: 14px;
  gap: 10px !important;
  overflow: hidden;
}

.sov-visual-hero {
  width: 100%;
  min-width: 0;
  padding: 12px 14px;
  flex: 0 0 auto;
}

.sov-visual-hero__row {
  width: 100%;
  min-width: 0;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  flex-wrap: nowrap;
}

.sov-visual-hero__row .sov-ui-section-heading {
  min-width: 0;
  flex: 1;
}

.sov-visual-frame {
  width: 100%;
  min-width: 0;
  min-height: 420px;
  padding: 0;
  flex: 1 1 auto;
  overflow: hidden;
}

.sov-visual-iframe {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 420px;
  border: 0;
  background: var(--bg);
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
    gap: 6px !important;
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
    min-height: 46px;
    margin: 0 !important;
    padding: 2px 7px;
    justify-content: flex-start;
  }

  .sov-brand-block > .sov-acronym-identity {
    width: 100%;
  }

  .sov-brand-block .sov-acronym-copy {
    max-width: 105px;
  }

  .sov-brand-block .sov-acronym-title {
    font-size: 15px !important;
    line-height: 1 !important;
    letter-spacing: 0;
  }

  .sov-brand-block .sov-acronym-expansion {
    display: -webkit-box;
    overflow: hidden;
    font-size: 10px;
    line-height: 1.15;
    white-space: normal;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }

  .sov-ui-version-badge {
    align-self: stretch;
    width: 100%;
    margin: 0 0 5px !important;
    padding-inline: 3px !important;
    justify-content: flex-start;
    font-size: 11px !important;
    font-variant-numeric: tabular-nums;
    line-height: 1.2 !important;
    color: var(--dim) !important;
    background: var(--bg) !important;
    border-color: var(--border) !important;
  }

  .sov-primary-nav {
    width: 100%;
    gap: 2px;
    flex-direction: column;
    align-items: stretch;
    border-radius: 8px;
    background: transparent;
    box-shadow: none;
  }

  .sov-nav-switch {
    width: 100%;
    min-height: 36px !important;
    height: 36px !important;
    padding: 0 7px !important;
    justify-content: flex-start !important;
    text-align: left !important;
    font-size: 12.5px !important;
    font-weight: 700 !important;
    line-height: 1.2 !important;
  }

  .sov-nav-switch .q-btn__content {
    width: 100%;
    gap: var(--sov-ui-icon-gap);
    flex-wrap: nowrap !important;
    flex-direction: row;
    justify-content: flex-start !important;
    text-align: left !important;
  }

  .sov-nav-switch .q-icon {
    width: var(--sov-ui-icon-column);
    min-width: var(--sov-ui-icon-column);
    margin: 0 !important;
    flex: 0 0 var(--sov-ui-icon-column);
    font-size: 18px;
    line-height: 1;
    text-align: center;
  }

  .sov-sidebar-caption {
    display: block;
    margin: 10px 8px 2px;
    padding-top: 10px;
    overflow: hidden;
    border-top: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
    font-size: 13px;
    font-weight: 800;
    line-height: 1.25;
    letter-spacing: 0;
    text-align: left;
    white-space: nowrap;
  }

  .les-top-tabs {
    width: 100%;
    height: auto !important;
    min-height: 0;
    flex: 1 1 0 !important;
    padding: 0;
    border-radius: 10px;
    background: color-mix(in srgb, var(--bg-panel) 82%, var(--bg-mod));
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--border) 68%, transparent);
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
    flex: 0 0 36px !important;
    width: 100%;
    height: 36px !important;
    min-height: 36px !important;
    margin: 1px 0;
    padding: 0 8px !important;
    border-radius: 7px;
    justify-content: flex-start !important;
    text-align: left !important;
    color: var(--text);
  }

  .les-top-tabs .q-tab:hover {
    background: color-mix(in srgb, var(--accent) 7%, transparent);
  }

  .les-top-tabs .q-tab--active {
    color: var(--accent) !important;
    background: color-mix(in srgb, var(--accent) 10%, var(--bg-panel));
  }

  .les-top-tabs .q-tab__content {
    min-width: 0;
    width: 100%;
    height: 36px !important;
    min-height: 36px !important;
    gap: var(--sov-ui-icon-gap) !important;
    align-items: center;
    flex-direction: row;
    justify-content: flex-start !important;
    text-align: left !important;
  }

  .les-top-tabs .q-icon {
    width: var(--sov-ui-icon-column);
    min-width: var(--sov-ui-icon-column);
    margin: 0 !important;
    flex: 0 0 var(--sov-ui-icon-column);
    font-size: 18px;
    line-height: 1;
    text-align: center;
  }

  .les-top-tabs .q-tab__label {
    display: block;
    overflow: hidden;
    font-size: 13px;
    font-weight: 650;
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
    padding-top: 10px;
    gap: 3px !important;
    align-items: stretch;
    justify-content: flex-start;
    border-top: 1px solid color-mix(in srgb, var(--border) 82%, transparent);
  }

  .sov-runtime-state,
  .sov-ui-header-utility,
  .sov-ui-header-secondary,
  .sov-ui-header-action {
    width: 100%;
    min-height: 36px;
    margin: 0 !important;
    padding: 0 8px !important;
    border-radius: 8px;
    color: var(--text) !important;
    font-family: var(--sov-ui-font-prose) !important;
    font-size: 12px !important;
    font-weight: 650 !important;
    line-height: 1.25;
    justify-content: flex-start !important;
    text-align: left !important;
  }

  .sov-runtime-state {
    gap: var(--sov-ui-icon-gap);
    align-items: center;
    flex-wrap: nowrap;
    background: color-mix(in srgb, var(--ok) 8%, var(--bg-panel));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ok) 18%, transparent);
  }

  .sov-runtime-dot {
    flex: 0 0 auto;
  }

  .sov-runtime-label {
    min-width: 0;
    color: var(--text);
    font-size: 12px;
    font-weight: 700;
    line-height: 1.25;
    white-space: nowrap;
  }

  .sov-ui-header-utility:hover,
  .sov-ui-header-secondary:hover,
  .sov-ui-header-action:hover {
    background: color-mix(in srgb, var(--accent) 7%, transparent);
  }

  .sov-ui-header-utility .q-btn__content,
  .sov-ui-header-secondary,
  .sov-ui-header-action .q-btn__content {
    width: 100%;
    gap: var(--sov-ui-icon-gap);
    flex-wrap: nowrap !important;
    justify-content: flex-start !important;
    text-align: left !important;
    white-space: nowrap !important;
  }

  .sov-ui-header-utility .q-icon,
  .sov-ui-header-secondary .q-icon,
  .sov-ui-header-action .q-icon {
    width: var(--sov-ui-icon-column);
    min-width: var(--sov-ui-icon-column);
    margin: 0 !important;
    flex: 0 0 var(--sov-ui-icon-column);
    font-size: 18px;
    text-align: center;
  }

  .sov-ui-header-secondary {
    display: flex;
    align-items: center;
    white-space: nowrap;
  }

  .sov-ui-header-account {
    margin-top: 3px !important;
    padding-inline: 8px !important;
    color: var(--ok) !important;
    background: color-mix(in srgb, var(--bg-mod) 72%, transparent);
  }

  .sov-ui-header-account .q-btn__content {
    min-width: 0;
    gap: var(--sov-ui-icon-gap) !important;
    overflow: hidden;
    font-size: 12px;
  }

  .sov-ui-header-account .q-btn__content > :not(.q-icon) {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
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

@media (max-width: 1100px) {
  .sov-checklist__setup {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .sov-mail-workbench {
    grid-template-columns: minmax(190px, .7fr) minmax(260px, .9fr) minmax(300px, 1.35fr);
  }
}

@media (max-width: 900px) {
  .sov-checklist__setup {
    grid-template-columns: minmax(0, 1fr);
  }
  .sov-checklist__head,
  .sov-checklist__run {
    align-items: stretch;
    flex-direction: column;
  }
  .sov-checklist__head .sov-ui-button--icon {
    align-self: flex-end;
  }
  .sov-checklist__run .sov-ui-button,
  .sov-checklist-dialog__actions .sov-ui-button {
    width: 100%;
  }
  .sov-checklist-dialog__actions {
    align-items: stretch;
    flex-direction: column;
  }
  .sov-ui-shell {
    max-width: 100vw;
    overflow-x: clip;
  }
  .sov-app-shell {
    display: flex !important;
    flex-direction: column;
  }
  .sov-ui-shell .sov-chat-identity {
    max-width: min(420px, 72vw);
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
  .sov-brand-block .sov-acronym-expansion {
    display: none !important;
  }
  .les-top-tabs {
    display: none !important;
  }
  .sov-mobile-sections-button {
    display: inline-flex !important;
    min-width: 40px;
    min-height: 40px;
    padding: 0 9px !important;
    color: var(--text) !important;
    font-size: 12px !important;
    font-weight: 700 !important;
  }
  .sov-topbar-icon-action {
    width: var(--sov-ui-hit);
    min-width: var(--sov-ui-hit) !important;
    height: var(--sov-ui-hit);
    min-height: var(--sov-ui-hit) !important;
  }
  .sov-mobile-sections-button .q-btn__content {
    gap: 5px;
    flex-wrap: nowrap;
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
  .sov-app-content > .q-panel-parent > .q-tab-panel,
  .sov-app-content .nicegui-tab-panel {
    padding: 0 !important;
  }
  .sov-app-content .sov-chat-shell {
    height: calc(100vh - 62px);
    min-height: 0;
    padding: 4px;
  }
  .sov-docs-sticky-ask { align-items: stretch; flex-direction: column; }
  .sov-docs-sticky-ask-button { width: 100%; }
  .sov-mail-page,
  .sov-mail-settings-page,
  .sov-tools-page {
    width: 100%;
    padding: 12px;
  }
  .sov-mail-hero,
  .sov-mail-settings-hero,
  .sov-tools-hero,
  .sov-mail-settings-section,
  .sov-tools-section {
    padding: 13px;
  }
  .sov-mail-status-strip { align-items: stretch; flex-wrap: wrap; }
  .sov-mail-status-copy { width: 100%; flex-basis: 100%; }
  .sov-mail-status-metric { flex: 1; }
  .sov-mail-collect-button { width: 100%; }
  .sov-mail-workbench {
    display: flex;
    min-height: 0;
    flex-direction: column;
  }
  .sov-mail-column {
    width: 100%;
    max-height: none;
  }
  .sov-mail-column--accounts { max-height: 310px; }
  .sov-mail-column--messages { max-height: 420px; }
  .sov-mail-settings-head,
  .sov-mail-account-card__row,
  .sov-tools-hero__row,
  .sov-tools-section__head {
    align-items: stretch;
    flex-direction: column;
  }
  .sov-mail-settings-connect,
  .sov-mail-settings-collect {
    width: 100%;
  }
  .sov-mail-collector-card {
    flex-wrap: wrap;
  }
  .sov-mail-collector-card__copy {
    min-width: calc(100% - 32px);
  }
  .sov-mail-account-card__actions,
  .sov-tools-actions {
    width: 100%;
    justify-content: flex-start;
  }
  .sov-tools-source__row {
    flex-wrap: wrap;
  }
  .sov-tools-source__copy {
    width: calc(100% - 32px);
    flex-basis: calc(100% - 32px);
  }
  .sov-tools-source__actions {
    width: 100%;
    padding-left: calc(var(--sov-ui-icon-column) + var(--sov-ui-icon-gap));
    justify-content: flex-start;
  }
  .sov-config-page {
    width: 100%;
    padding: 12px;
  }
  .sov-config-hero {
    padding: 14px;
  }
  .sov-config-hero__row,
  .sov-config-disclosure__header {
    flex-direction: column;
    align-items: stretch;
  }
  .sov-config-hero__actions,
  .sov-config-disclosure__actions {
    width: 100%;
  }
  .sov-config-run .q-btn__content {
    flex-wrap: nowrap;
    white-space: nowrap;
  }
  .sov-config-status-strip {
    grid-template-columns: minmax(0, 1fr);
  }
  .sov-config-status-strip__metrics {
    min-width: 0;
    border-top: 1px solid var(--border);
    border-left: 0;
  }
  .sov-config-contours {
    grid-template-columns: minmax(0, 1fr);
  }
  .sov-config-page .diag-acronym-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .sov-datasets-page {
    width: 100%;
    padding: 12px;
  }
  .sov-datasets-hero__row {
    align-items: flex-start;
  }
  .sov-datasets-hero .sov-acronym-identity {
    max-width: 100%;
  }
  .sov-datasets-hero .sov-acronym-expansion {
    overflow: visible;
    text-overflow: clip;
    white-space: normal;
  }
  .sov-dataset-summary {
    grid-template-columns: minmax(0, 1fr);
  }
  .sov-dataset-summary__metrics {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    border-top: 1px solid var(--border);
    border-left: 0;
  }
  .sov-dataset-summary__metric:nth-child(4) {
    border-top: 1px solid var(--border);
    border-left: 0;
  }
  .sov-dataset-summary__metric:nth-child(5),
  .sov-dataset-summary__metric:nth-child(6) {
    border-top: 1px solid var(--border);
  }
  .sov-dataset-toolbar {
    grid-template-columns: minmax(0, 1fr);
  }
  .sov-dataset-filters {
    width: 100%;
    overflow-x: auto;
  }
  .sov-dataset-filter {
    flex: 1 0 auto;
  }
  .sov-dataset-row {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "head"
      "facts"
      "progress"
      "note"
      "actions";
  }
  .sov-dataset-row__actions {
    width: 100%;
    justify-content: flex-start;
  }
  .sov-dataset-index-status {
    width: 100%;
    flex-basis: 100%;
  }
  .sov-dataset-settings__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .sov-history-page,
  .sov-access-page {
    width: 100%;
    padding: 12px;
  }
  .sov-history-hero__row,
  .sov-history-list-head,
  .sov-access-hero__row,
  .sov-access-registry__head {
    align-items: stretch;
    flex-direction: column;
  }
  .sov-history-row,
  .sov-access-key-row {
    align-items: stretch;
    flex-direction: column;
  }
  .sov-history-row__open {
    width: 100%;
  }
  .sov-access-form {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .sov-access-form__actions,
  .sov-access-key-row__actions {
    width: 100%;
    justify-content: flex-start;
  }
  .sov-visual-page {
    padding: 8px;
  }
  .sov-visual-hero__row {
    align-items: stretch;
    flex-direction: column;
  }
  .sov-visual-hero__row .sov-ui-button {
    width: 100%;
  }
}

@media (max-width: 520px) {
  .sov-brand-block .sov-acronym-title,
  .sov-brand-block .sov-acronym-expansion {
    display: none;
  }
  .les-top-tabs .q-tab__label {
    display: none;
  }
  .les-top-tabs .q-tab {
    width: 44px;
  }
  .sov-composer-key-hint {
    display: none;
  }
  .sov-config-status-strip__metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .sov-config-metric:nth-child(3) {
    border-top: 1px solid var(--border);
    border-left: 0;
  }
  .sov-config-metric:nth-child(4) {
    border-top: 1px solid var(--border);
  }
  .sov-config-disclosure__actions {
    flex-direction: column;
  }
  .sov-config-disclosure__actions .sov-ui-button {
    width: 100%;
  }
  .sov-datasets-hero__row {
    display: grid !important;
    grid-template-columns: minmax(0, 1fr);
    flex-wrap: wrap;
  }
  .sov-datasets-hero .sov-acronym-identity,
  .sov-datasets-hero .sov-acronym-copy {
    width: 100%;
    min-width: 0;
  }
  .sov-datasets-hero .sov-acronym-expansion,
  .sov-datasets-hero__detail {
    overflow-wrap: anywhere;
  }
  .sov-dataset-add {
    width: 100%;
    max-width: 100%;
  }
  .sov-dataset-summary__metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .sov-dataset-summary__metric:nth-child(3),
  .sov-dataset-summary__metric:nth-child(5) {
    border-top: 1px solid var(--border);
    border-left: 0;
  }
  .sov-dataset-summary__metric:nth-child(4) {
    border-left: 1px solid var(--border);
  }
  .sov-dataset-row__head {
    align-items: flex-start;
  }
  .sov-dataset-row__facts {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    row-gap: 8px;
  }
  .sov-dataset-row__actions .sov-ui-button--secondary {
    flex: 1 1 auto;
  }
  .sov-dataset-settings__grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .sov-dataset-settings__switches {
    align-items: stretch;
    flex-direction: column;
  }
  .sov-access-form {
    grid-template-columns: minmax(0, 1fr);
  }
  .sov-access-form__actions {
    align-items: stretch;
    flex-direction: column;
  }
  .sov-access-form__actions .sov-ui-button,
  .sov-access-key-row__actions .sov-ui-button {
    width: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  ::view-transition-old(root),
  ::view-transition-new(root) {
    animation-duration: .001ms !important;
  }

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
