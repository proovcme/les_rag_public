"""
С.О.В.У.Ш.К.А. v5.0 — CSS стили
"""

_DARK_THEME = {
    "--bg":       "#050608",
    "--bg-panel": "#10141b",
    "--bg-mod":   "#18212c",
    "--text":     "#f8fbff",
    "--dim":      "#d2deea",
    "--border":   "#55708a",
    "--accent":   "#38bdf8",
    "--ok":       "#22e06f",
    "--pauk":     "#c084fc",
    "--warn":     "#ffd166",
    "--err":      "#ff6b6b",
}

_LIGHT_THEME = {
    "--bg":       "#f7fafc",
    "--bg-panel": "#ffffff",
    "--bg-mod":   "#e6edf5",
    "--text":     "#0d1117",
    "--dim":      "#263544",
    "--border":   "#8aa2b8",
    "--accent":   "#005fcc",
    "--ok":       "#007a3d",
    "--pauk":     "#7c3aed",
    "--warn":     "#8a5400",
    "--err":      "#b4232a",
}


def theme_vars_css(dark: bool = True) -> str:
    """Возвращает <style> блок с CSS-переменными для нужной темы.
    Вызывать внутри main_page() через ui.add_head_html() — синхронно, без flash."""
    vars_ = _DARK_THEME if dark else _LIGHT_THEME
    body_bg = vars_["--bg"]
    body_fg = vars_["--text"]
    lines = "\n".join(f"  {k}: {v};" for k, v in vars_.items())
    return (
        f"<style>\n:root {{\n{lines}\n"
        f"  --font: 'Courier New', Courier, monospace;\n}}\n"
        f"body {{ background:{body_bg}; color:{body_fg}; }}\n</style>"
    )


CUSTOM_CSS = """
<style>
@font-face {
  font-family: 'ISOCPEUR';
  src: url('/static/fonts/ISOCPEUR.ttf') format('truetype');
  font-weight: normal;
  font-style: normal;
}
:root {
  --bg:       #050608;
  --bg-panel: #10141b;
  --bg-mod:   #18212c;
  --text:     #f8fbff;
  --dim:      #d2deea;
  --border:   #55708a;
  --accent:   #38bdf8;
  --ok:       #22e06f;
  --pauk:     #c084fc;
  --warn:     #ffd166;
  --err:      #ff6b6b;
  --font:     'Courier New', Courier, monospace;
  --font-chat: 'ISOCPEUR', 'Courier New', Courier, monospace;
}
body, .nicegui-content { font-family: var(--font) !important; }
.les-header {
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.les-brand { font-weight: 900; font-size: 1.1rem; color: var(--accent); text-shadow: 0 0 12px rgba(56,189,248,.35); }
.kpi-box {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 16px 20px;
  min-width: 120px;
}
.kpi-val  { font-size: 1.6rem; font-weight: 900; line-height: 1; }
.kpi-lbl  { font-size: .62rem; text-transform: uppercase; color: var(--dim); margin-top: 5px; letter-spacing: .5px; }
.card-les {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
}
.section-title {
  font-size: .68rem;
  font-weight: 900;
  text-transform: uppercase;
  color: var(--dim);
  letter-spacing: .4px;
}
.tag-ok   { background:rgba(16,185,129,.15); color:var(--ok);   border:1px solid rgba(16,185,129,.3); border-radius:10px; padding:2px 8px; font-size:.6rem; font-weight:700; }
.tag-warn { background:rgba(245,158,11,.15); color:var(--warn); border:1px solid rgba(245,158,11,.3); border-radius:10px; padding:2px 8px; font-size:.6rem; font-weight:700; }
.tag-err  { background:rgba(239,68,68,.15);  color:var(--err);  border:1px solid rgba(239,68,68,.3);  border-radius:10px; padding:2px 8px; font-size:.6rem; font-weight:700; }
.tag-dim  { background:var(--bg-mod); color:var(--dim); border:1px solid var(--border); border-radius:10px; padding:2px 8px; font-size:.6rem; font-weight:700; }
.tag-acc  { background:rgba(59,130,246,.15); color:var(--accent); border:1px solid rgba(59,130,246,.3); border-radius:10px; padding:2px 8px; font-size:.6rem; font-weight:700; }
.tag-pauk { background:rgba(139,92,246,.15); color:var(--pauk);  border:1px solid rgba(139,92,246,.3); border-radius:10px; padding:2px 8px; font-size:.6rem; font-weight:700; }
.mode-rag  { background:rgba(16,185,129,.1); border:1px solid var(--ok);   color:var(--ok);   border-radius:4px; padding:5px 14px; font-weight:900; font-size:.7rem; cursor:pointer; }
.mode-code { background:rgba(139,92,246,.1); border:1px solid var(--pauk); color:var(--pauk); border-radius:4px; padding:5px 14px; font-weight:900; font-size:.7rem; cursor:pointer; }
.hbar { height:16px; background:var(--border); border-radius:4px; overflow:hidden; display:flex; }
.hbar-seg { height:100%; transition:width .5s; }
.dot { width:8px; height:8px; border-radius:50%; display:inline-block; background:var(--ok); }
.dot-warn { background:var(--warn); }
.dot-err  { background:var(--err); }
.dot-idle { background:var(--border); }
.mermaid-wrap { background:var(--bg-mod); border:1px solid var(--border); border-radius:8px; padding:16px; }
.output-table { width:100%; border-collapse:collapse; font-size:.75rem; }
.output-table th { padding:8px 12px; background:var(--bg-mod); border-bottom:1px solid var(--border); color:var(--dim); font-weight:700; text-transform:uppercase; font-size:.6rem; letter-spacing:.4px; text-align:left; }
.output-table td { padding:7px 12px; border-bottom:1px solid var(--border); color:var(--text); vertical-align:top; }
.output-table tr:hover td { background:var(--bg-mod); }
.chat-msg-user { align-self:flex-end; background:var(--bg-mod); color:var(--text) !important; border:1px solid var(--border); border-right:3px solid var(--pauk); border-radius:6px; padding:10px 14px; max-width:80%; font-family:var(--font-chat) !important; font-size:.9rem; line-height:1.6; }
.chat-msg-ai   { align-self:flex-start; background:var(--bg-panel); color:var(--text) !important; border:1px solid var(--border); border-left:3px solid var(--accent); border-radius:6px; padding:10px 14px; max-width:85%; font-family:var(--font-chat) !important; font-size:.9rem; line-height:1.6; }
.chat-msg-sys  { align-self:center; color:var(--dim); font-size:.72rem; border:1px solid var(--border); border-radius:4px; padding:4px 12px; font-family:var(--font-chat); }
.sov-chat-shell {
  position: relative;
  width: 100%;
  height: calc(100vh - 92px);
  min-height: 620px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 380px);
  gap: 14px;
  padding: 14px;
  background:
    radial-gradient(circle at 14% 10%, rgba(56,189,248,.10), transparent 28%),
    linear-gradient(180deg, rgba(16,20,27,.96), var(--bg));
  overflow: hidden;
}
.sov-chat-main, .sov-artifacts-panel, .sov-history-drawer {
  background: rgba(16,20,27,.86);
  border: 1px solid rgba(138,162,184,.32);
  box-shadow: 0 18px 60px rgba(0,0,0,.24), inset 0 1px 0 rgba(255,255,255,.05);
  backdrop-filter: blur(14px);
}
.sov-chat-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  border-radius: 8px;
  overflow: hidden;
}
.sov-chat-topbar {
  min-height: 58px;
  padding: 10px 14px;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(138,162,184,.22);
  background: rgba(24,33,44,.58);
}
.sov-chat-title { color: var(--text); font-size: .92rem; font-weight: 900; letter-spacing: .08em; }
.sov-chat-subtitle { color: var(--dim); font-size: .68rem; }
.sov-chat-scroll {
  flex: 1;
  min-height: 0;
  background: linear-gradient(180deg, rgba(5,6,8,.18), rgba(5,6,8,.44));
}
.sov-chat-thread {
  width: 100%;
  min-height: 100%;
  gap: 13px;
  padding: 22px 24px 150px;
}
.sov-composer {
  margin: 0 18px 18px;
  padding: 10px;
  border: 1px solid rgba(138,162,184,.32);
  border-radius: 8px;
  background: rgba(5,6,8,.78);
  box-shadow: 0 18px 42px rgba(0,0,0,.26);
}
.sov-composer-input {
  width: 100%;
  color: var(--text);
  font-family: var(--font-chat) !important;
  font-size: .92rem;
}
.sov-composer-actions {
  width: 100%;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
}
.sov-composer-actions .q-btn:last-child {
  background: linear-gradient(135deg, rgba(56,189,248,.95), rgba(34,224,111,.86)) !important;
  color: #041014 !important;
  font-weight: 900;
}
.sov-icon-btn { color: var(--dim) !important; }
.sov-chip {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 9px;
  border-radius: 4px;
  border: 1px solid rgba(56,189,248,.36);
  color: var(--accent);
  background: rgba(56,189,248,.10);
  font-size: .62rem;
  font-weight: 900;
}
.sov-chip-soft {
  border-color: rgba(192,132,252,.32);
  color: var(--pauk);
  background: rgba(192,132,252,.10);
}
.sov-artifacts-panel {
  min-width: 0;
  border-radius: 8px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
}
.sov-panel-title {
  color: var(--text);
  font-size: .76rem;
  font-weight: 900;
  text-transform: uppercase;
  letter-spacing: .12em;
}
.sov-muted {
  color: var(--dim);
  opacity: .78;
  font-size: .68rem;
  line-height: 1.45;
}
.sov-artifacts-body {
  flex: 1;
  width: 100%;
  min-height: 0;
  overflow-y: auto;
  gap: 12px;
  align-items: stretch !important;
}
.sov-artifacts-body > * {
  width: 100%;
}
.sov-artifact-empty {
  width: 100%;
  min-height: 220px;
  border: 1px dashed rgba(138,162,184,.35);
  border-radius: 8px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 8px;
  background: rgba(5,6,8,.22);
}
.sov-artifact-empty-title {
  color: var(--text);
  font-size: 1rem;
  font-weight: 900;
}
.sov-artifact-loader {
  width: 100%;
  height: 3px;
  border-radius: 99px;
  overflow: hidden;
  background: rgba(138,162,184,.18);
}
.sov-artifact-loader::after {
  content: "";
  display: block;
  width: 36%;
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--ok));
  animation: sovload 1.1s infinite ease-in-out;
}
@keyframes sovload {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(280%); }
}
.sov-artifact-card {
  width: 100%;
  background: rgba(5,6,8,.34) !important;
  border: 1px solid rgba(138,162,184,.32) !important;
  border-radius: 8px !important;
  box-shadow: none !important;
  gap: 12px;
}
.sov-artifact-markdown {
  color: var(--text);
  font-size: .82rem;
  line-height: 1.6;
}
.sov-artifact-table {
  width: 100%;
  background: var(--bg-panel);
  color: var(--text);
  font-size: .72rem;
}
.sov-svg-preview {
  width: 100%;
  overflow: auto;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px;
}
.sov-svg-preview svg { max-width: 100%; height: auto; }
.sov-history-drawer {
  position: absolute;
  z-index: 20;
  left: 14px;
  top: 14px;
  bottom: 14px;
  width: min(390px, calc(100vw - 32px));
  border-radius: 8px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.sov-history-list {
  overflow-y: auto;
  min-height: 0;
}
.sov-session-card {
  width: 100%;
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 11px 12px;
  border-radius: 8px;
  border: 1px solid rgba(138,162,184,.28);
  background: rgba(5,6,8,.32);
  cursor: pointer;
}
.sov-session-card:hover, .sov-session-card-active {
  border-color: rgba(56,189,248,.7);
  background: rgba(56,189,248,.10);
}
.sov-session-title {
  color: var(--text);
  font-size: .74rem;
  line-height: 1.35;
  font-weight: 700;
}
.sov-session-meta {
  color: var(--dim);
  font-size: .62rem;
}
.sov-advanced-dialog {
  width: min(920px, calc(100vw - 32px));
  max-height: min(820px, calc(100vh - 40px));
  background: rgba(16,20,27,.97) !important;
  border: 1px solid rgba(138,162,184,.34) !important;
  border-radius: 8px !important;
  color: var(--text);
}
.sov-advanced-scroll {
  width: 100%;
  max-height: calc(100vh - 210px);
}
.sov-control-card {
  background: rgba(5,6,8,.26) !important;
  border: 1px solid rgba(138,162,184,.28) !important;
  border-radius: 8px !important;
  box-shadow: none !important;
  gap: 10px;
}
.sov-format-btn {
  width: 100%;
  min-height: 38px;
  border: 1px solid rgba(138,162,184,.28) !important;
  border-radius: 6px !important;
  color: var(--dim) !important;
  justify-content: flex-start !important;
}
.sov-format-btn-active {
  border-color: rgba(56,189,248,.8) !important;
  color: var(--accent) !important;
  background: rgba(56,189,248,.12) !important;
}
.sov-template-preview,
.sov-prompt-preview {
  width: 100%;
  max-height: 160px;
  overflow: auto;
  border: 1px solid rgba(138,162,184,.28);
  border-radius: 8px;
  background: rgba(5,6,8,.34);
  padding: 10px;
}
.sov-template-preview pre,
.sov-prompt-preview pre {
  margin: 0;
  color: var(--dim);
  white-space: pre-wrap;
  font-size: .68rem;
}
.sov-tree-row {
  display: flex;
  gap: 6px;
  align-items: baseline;
  padding: 3px 0;
}
.sov-tree-mark { color: var(--accent); font-size: .72rem; }
.sov-tree-name { color: var(--text); font-size: .74rem; font-weight: 800; }
.sov-tree-desc { color: var(--dim); font-size: .68rem; }
@media (max-width: 980px) {
  .sov-chat-shell {
    grid-template-columns: 1fr;
    height: auto;
    min-height: calc(100vh - 92px);
    overflow: visible;
  }
  .sov-artifacts-panel {
    min-height: 340px;
  }
  .sov-chat-main {
    min-height: 680px;
  }
}
.src-tag { font-size:.6rem; font-weight:700; padding:2px 6px; border:1px solid var(--ok); color:var(--ok); border-radius:4px; margin-right:4px; }
.src-tag-err { border-color:var(--err); color:var(--err); }
.typing::after { content:'▋'; animation:blink 1s step-end infinite; opacity:.7; margin-left:4px; }
@keyframes blink { 50%{opacity:0} }
/* Quasar: текст в полях ввода */
.q-field__native, .q-field__input, .q-field__prefix, .q-field__suffix,
.q-field--dark .q-field__native, .q-field--dark .q-field__input {
  color: var(--text) !important;
}
/* Quasar: лейблы, заголовки, подписи */
.q-item__label, .q-item__label--header, .q-field__label {
  color: var(--dim) !important;
  opacity: 1 !important;
}
/* Quasar: основной текст в списках и кнопках */
.q-item__section--main, .q-btn__content, .q-tab__label {
  color: var(--text) !important;
  opacity: 1 !important;
}
/* Quasar: select/option текст */
.q-select__dropdown-icon, .q-field__marginal {
  color: var(--dim) !important;
}
/* Quasar select — выпадающий список */
.q-menu { background: var(--bg-panel) !important; border: 1px solid var(--border) !important; }
.q-item  { color: var(--text) !important; }
.q-item:hover, .q-item--active { background: var(--bg-mod) !important; color: var(--accent) !important; }
/* Quasar select — выбранное значение */
.q-field__native span, .q-select .q-field__native {
  color: var(--text) !important;
}
/* Убираем opacity у disabled-like элементов */
.q-field--readonly .q-field__native,
.q-field--disabled .q-field__native {
  opacity: 0.85 !important;
  color: var(--text) !important;
}
/* Tabs */
.q-tab { color: var(--dim) !important; opacity: 1 !important; }
.q-tab--active { color: var(--accent) !important; background: rgba(56,189,248,.10) !important; }
/* Generic text */
.q-card, .q-card__section { color: var(--text) !important; }
</style>
"""
