"""
С.О.В.У.Ш.К.А. v5.0 — CSS стили
"""

_DARK_THEME = {
    "--bg":       "#08090b",
    "--bg-panel": "#12151a",
    "--bg-mod":   "#1a1e25",
    "--text":     "#f0f4f8",
    "--dim":      "#c4cfd9",
    "--border":   "#3d4f63",
    "--accent":   "#60a5fa",
    "--ok":       "#34d399",
    "--pauk":     "#a78bfa",
    "--warn":     "#fbbf24",
    "--err":      "#f87171",
}

_LIGHT_THEME = {
    "--bg":       "#f6f8fa",
    "--bg-panel": "#ffffff",
    "--bg-mod":   "#eaeef2",
    "--text":     "#0d1117",
    "--dim":      "#2d3a46",
    "--border":   "#b0bec8",
    "--accent":   "#0550ae",
    "--ok":       "#116329",
    "--pauk":     "#6639ba",
    "--warn":     "#7d4e00",
    "--err":      "#a0111f",
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
  --bg:       #08090b;
  --bg-panel: #12151a;
  --bg-mod:   #1a1e25;
  --text:     #f0f4f8;
  --dim:      #c4cfd9;
  --border:   #3d4f63;
  --accent:   #60a5fa;
  --ok:       #34d399;
  --pauk:     #a78bfa;
  --warn:     #fbbf24;
  --err:      #f87171;
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
.les-brand { font-weight: 900; font-size: 1.1rem; color: var(--accent); }
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
.chat-msg-user { align-self:flex-end; background:var(--border); color:#f0f4f8 !important; border-right:3px solid var(--pauk); border-radius:6px; padding:10px 14px; max-width:80%; font-family:var(--font-chat) !important; font-size:.9rem; line-height:1.6; }
.chat-msg-ai   { align-self:flex-start; background:var(--bg-panel); color:#f0f4f8 !important; border:1px solid var(--border); border-left:3px solid var(--accent); border-radius:6px; padding:10px 14px; max-width:85%; font-family:var(--font-chat) !important; font-size:.9rem; line-height:1.6; }
.chat-msg-sys  { align-self:center; color:var(--dim); font-size:.72rem; border:1px solid var(--border); border-radius:4px; padding:4px 12px; font-family:var(--font-chat); }
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
.q-tab--active { color: var(--accent) !important; }
/* Generic text */
.q-card, .q-card__section { color: var(--text) !important; }
</style>
"""
