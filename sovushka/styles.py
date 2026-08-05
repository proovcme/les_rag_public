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
    "--accent":   "#34d399",
    "--ok":       "#22e06f",
    "--pauk":     "#c084fc",
    "--warn":     "#ffd166",
    "--err":      "#ff6b6b",
    "--shell-bg": "radial-gradient(circle at 14% 10%, rgba(52,211,153,.10), transparent 28%), linear-gradient(180deg, rgba(16,20,27,.96), #050608)",
    "--panel-glass": "rgba(16,20,27,.88)",
    "--panel-top": "rgba(24,33,44,.70)",
    "--scroll-bg": "linear-gradient(180deg, rgba(5,6,8,.18), rgba(5,6,8,.44))",
    "--composer-bg": "rgba(5,6,8,.82)",
    "--artifact-bg": "rgba(5,6,8,.28)",
    "--card-bg": "rgba(5,6,8,.34)",
    "--input-bg": "rgba(5,6,8,.58)",
    "--shadow-strong": "0 18px 60px rgba(0,0,0,.24), inset 0 1px 0 rgba(255,255,255,.05)",
}

_LIGHT_THEME = {
    "--bg":       "#f3f6f2",
    "--bg-panel": "#ffffff",
    "--bg-mod":   "#edf3ee",
    "--text":     "#17231c",
    "--dim":      "#405247",
    "--border":   "#d5dfd7",
    "--accent":   "#176b42",
    "--ok":       "#176b42",
    "--pauk":     "#6d28d9",
    "--warn":     "#8a4b00",
    "--err":      "#b91c1c",
    "--shell-bg": "#f3f6f2",
    "--panel-glass": "#ffffff",
    "--panel-top": "#fbfcfa",
    "--scroll-bg": "#f7f9f6",
    "--composer-bg": "#ffffff",
    "--artifact-bg": "#f7f9f6",
    "--card-bg": "#ffffff",
    "--input-bg": "#ffffff",
    "--shadow-strong": "0 1px 2px rgba(20,52,34,.05), 0 8px 24px rgba(20,52,34,.05)",
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
        f"  --font: ui-monospace, 'SFMono-Regular', Menlo, Consolas, 'Courier New', monospace;\n"
        f"  --font-chat: ui-monospace, 'SFMono-Regular', Menlo, Consolas, 'Courier New', monospace;\n}}\n"
        f"body {{ background:{body_bg}; color:{body_fg}; }}\n</style>"
    )


CUSTOM_CSS = """
<style>
:root {
  --bg:       #050608;
  --bg-panel: #10141b;
  --bg-mod:   #18212c;
  --text:     #f8fbff;
  --dim:      #d2deea;
  --border:   #55708a;
  --accent:   #34d399;
  --ok:       #22e06f;
  --pauk:     #c084fc;
  --warn:     #ffd166;
  --err:      #ff6b6b;
  --shell-bg: radial-gradient(circle at 14% 10%, rgba(52,211,153,.10), transparent 28%), linear-gradient(180deg, rgba(16,20,27,.96), #050608);
  --panel-glass: rgba(16,20,27,.88);
  --panel-top: rgba(24,33,44,.70);
  --scroll-bg: linear-gradient(180deg, rgba(5,6,8,.18), rgba(5,6,8,.44));
  --composer-bg: rgba(5,6,8,.82);
  --artifact-bg: rgba(5,6,8,.28);
  --card-bg: rgba(5,6,8,.34);
  --input-bg: rgba(5,6,8,.58);
  --shadow-strong: 0 18px 60px rgba(0,0,0,.24), inset 0 1px 0 rgba(255,255,255,.05);
  --font:     ui-monospace, 'SFMono-Regular', Menlo, Consolas, 'Courier New', monospace;
  --font-chat: ui-monospace, 'SFMono-Regular', Menlo, Consolas, 'Courier New', monospace;
}
body, .nicegui-content { font-family: var(--font) !important; color: var(--text) !important; }
@media (min-width: 1000px) {
  html { font-size: 12px !important; }
}
body, .nicegui-content, .q-page, .q-layout, .q-card, .q-dialog, .q-menu,
.q-table, .q-item, .sov-chat-md, .sov-chat-message-text, .sov-artifact-markdown,
.card-les, .kpi-box, .diag-node, .diag-acronym-item {
  user-select: text;
  -webkit-user-select: text;
}
.q-btn, .q-tab, [role="button"], button {
  user-select: none;
  -webkit-user-select: none;
}
.les-header {
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.les-brand { font-weight: 900; font-size: 1.1rem; color: var(--accent); text-shadow: 0 0 12px rgba(52,211,153,.35); }
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
.tag-acc  { background:rgba(52,211,153,.15); color:var(--accent); border:1px solid rgba(52,211,153,.3); border-radius:10px; padding:2px 8px; font-size:.6rem; font-weight:700; }
.tag-pauk { background:rgba(139,92,246,.15); color:var(--pauk);  border:1px solid rgba(139,92,246,.3); border-radius:10px; padding:2px 8px; font-size:.6rem; font-weight:700; }
.les-fuse-board {
  position: relative;
  overflow: hidden;
  background:
    linear-gradient(90deg, rgba(34,224,111,.09), rgba(52,211,153,.07) 52%, rgba(255,209,102,.06)),
    var(--bg-panel);
}
.les-fuse-board::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  border-top: 1px solid rgba(248,251,255,.10);
}
.les-fuse-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
}
.les-fuse {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 9px 10px;
  background: rgba(5,6,8,.32);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.05);
}
.les-fuse-ok { border-color: rgba(34,224,111,.55); background: rgba(34,224,111,.08); }
.les-fuse-warn { border-color: rgba(255,209,102,.60); background: rgba(255,209,102,.08); }
.les-fuse-err { border-color: rgba(255,107,107,.66); background: rgba(255,107,107,.09); }
.les-fuse-cap {
  color: var(--dim);
  font-size: .54rem;
  font-weight: 900;
  text-transform: uppercase;
}
.les-fuse-val {
  color: var(--text);
  font-size: .9rem;
  font-weight: 900;
  margin-top: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.les-fuse-detail {
  color: var(--dim);
  font-size: .56rem;
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mode-rag  { background:rgba(16,185,129,.1); border:1px solid var(--ok);   color:var(--ok);   border-radius:4px; padding:5px 14px; font-weight:900; font-size:.7rem; cursor:pointer; }
.mode-code { background:rgba(139,92,246,.1); border:1px solid var(--pauk); color:var(--pauk); border-radius:4px; padding:5px 14px; font-weight:900; font-size:.7rem; cursor:pointer; }
.hbar { height:16px; background:var(--border); border-radius:4px; overflow:hidden; display:flex; }
.hbar-seg { height:100%; transition:width .5s; }
.dot { width:8px; height:8px; border-radius:50%; display:inline-block; background:var(--ok); }
.dot-warn { background:var(--warn); }
.dot-err  { background:var(--err); }
.dot-idle { background:var(--border); }
.mermaid-wrap { background:var(--bg-mod); border:1px solid var(--border); border-radius:8px; padding:16px; }
.les-map-page {
  min-height: calc(100vh - 112px);
  padding: 28px clamp(18px, 4vw, 54px) 34px;
  gap: 18px;
  background: var(--bg);
}
.les-map-head {
  max-width: 1440px;
  margin: 0 auto;
}
.les-map-title {
  font-size: 1.05rem;
  font-weight: 900;
  letter-spacing: .08em;
  color: var(--text);
}
.les-map-subtitle {
  font-size: .72rem;
  color: var(--dim);
}
.les-map-layout {
  max-width: 1440px;
  margin: 0 auto;
  gap: 16px;
  align-items: stretch;
}
.les-map-rail,
.les-map-preview-shell {
  min-width: 0;
  background: var(--panel-glass);
  border: 1px solid rgba(138,162,184,.34);
  border-radius: 8px;
  box-shadow: var(--shadow-strong);
  padding: 14px;
}
.les-map-preview-shell {
  min-height: 680px;
}
.les-map-selected {
  color: var(--text);
  font-size: .96rem;
  font-weight: 900;
}
.les-map-meta {
  min-height: 42px;
  color: var(--dim);
  font-size: .68rem;
  line-height: 1.45;
}
.les-map-preset {
  height: 42px;
  justify-content: flex-start;
  background: rgba(24,33,44,.56) !important;
  border: 1px solid rgba(138,162,184,.26);
  border-radius: 6px;
  color: var(--dim) !important;
  font-size: .72rem;
  font-weight: 800;
}
.les-map-preset:hover,
.les-map-preset-active {
  color: var(--text) !important;
  border-color: var(--accent);
  background: rgba(52,211,153,.12) !important;
}
.les-map-action,
.les-map-action-muted {
  font-size: .7rem;
  font-weight: 800;
}
.les-map-action {
  color: var(--ok) !important;
  border-color: var(--ok) !important;
}
.les-map-action-muted {
  color: var(--dim) !important;
}
.les-map-source {
  background: rgba(5,6,8,.28);
  border: 1px solid rgba(138,162,184,.22);
  border-radius: 6px;
  color: var(--text);
}
.les-map-editor {
  height: 340px;
  border: 1px solid rgba(138,162,184,.28);
  border-radius: 6px;
  overflow: hidden;
}
.les-map-preview {
  width: 100%;
  box-sizing: border-box;
  flex: 1;
  min-height: 620px;
  overflow: auto;
  background: linear-gradient(180deg, rgba(5,6,8,.48), rgba(5,6,8,.22));
  border: 1px solid rgba(138,162,184,.28);
  border-radius: 8px;
  padding: 26px;
}
.les-map-mermaid {
  width: 100%;
  min-height: 560px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.les-map-mermaid svg {
  width: min(100%, 980px) !important;
  max-width: 100%;
  height: auto;
}
.diag-map-wrap {
  width: 100%;
  overflow: hidden;
  background: linear-gradient(180deg, rgba(5,6,8,.42), rgba(13,24,36,.32));
  border: 1px solid rgba(138,162,184,.28);
  border-radius: 8px;
  padding: 10px;
}
.diag-live-map {
  width: 100%;
  display: grid;
  grid-template-columns: minmax(150px, .75fr) 24px minmax(170px, .8fr) 24px minmax(420px, 2.2fr);
  gap: 8px;
  align-items: stretch;
}
.diag-map-stack {
  display: grid;
  grid-template-rows: 1fr 1fr;
  gap: 8px;
}
.diag-map-proxy {
  display: flex;
  align-items: center;
  justify-content: center;
}
.diag-map-groups {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.diag-map-group {
  min-width: 0;
  border: 1px solid rgba(138,162,184,.22);
  border-radius: 8px;
  background: rgba(10,17,25,.48);
  padding: 7px;
}
.diag-map-group-title {
  color: var(--dim);
  font-size: .58rem;
  font-weight: 900;
  text-transform: uppercase;
  letter-spacing: 0;
  margin-bottom: 5px;
}
.diag-map-group-body {
  display: grid;
  gap: 5px;
}
.diag-map-arrow {
  position: relative;
  min-height: 100%;
}
.diag-map-arrow::before {
  content: "";
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, rgba(52,211,153,.14), rgba(52,211,153,.85));
  transform: translateY(-50%);
}
.diag-map-arrow::after {
  content: "";
  position: absolute;
  top: calc(50% - 5px);
  right: 0;
  border-top: 5px solid transparent;
  border-bottom: 5px solid transparent;
  border-left: 7px solid rgba(110,231,183,.9);
}
.diag-node {
  --node-color: rgba(138,162,184,.62);
  min-width: 0;
  min-height: 42px;
  border: 1px solid color-mix(in srgb, var(--node-color) 58%, transparent);
  border-radius: 8px;
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--node-color) 10%, transparent), rgba(5,6,8,.22)),
    rgba(15,24,34,.72);
  padding: 6px 7px;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.02);
}
.diag-node-hub {
  width: 100%;
  min-height: 92px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.diag-node-head {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}
.diag-node-dot {
  width: 7px;
  height: 7px;
  border-radius: 99px;
  flex: 0 0 auto;
  background: var(--node-color);
  box-shadow: 0 0 14px color-mix(in srgb, var(--node-color) 65%, transparent);
}
.diag-node-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
  font-size: .68rem;
  font-weight: 900;
  letter-spacing: 0;
}
.diag-node-state {
  margin-left: auto;
  border: 1px solid color-mix(in srgb, var(--node-color) 52%, transparent);
  border-radius: 4px;
  padding: 1px 4px;
  color: var(--node-color);
  font-size: .48rem;
  font-weight: 900;
}
.diag-node-sub {
  margin-top: 3px;
  color: var(--dim);
  font-size: .56rem;
  line-height: 1.28;
}
.diag-node-ok { --node-color: var(--ok); }
.diag-node-warn { --node-color: var(--warn); }
.diag-node-err { --node-color: var(--err); }
.diag-node-idle { --node-color: #6f8da8; }
.diag-acronym-grid {
  width: 100%;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}
.diag-acronym-item {
  min-width: 0;
  min-height: 88px;
  border: 1px solid rgba(138,162,184,.24);
  border-radius: 8px;
  background: rgba(10,17,25,.46);
  padding: 8px;
}
.diag-acronym-code {
  color: var(--accent);
  font-size: .66rem;
  font-weight: 900;
  letter-spacing: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.diag-acronym-full {
  margin-top: 4px;
  color: var(--text);
  font-size: .58rem;
  line-height: 1.32;
}
.diag-acronym-role {
  margin-top: 5px;
  color: var(--dim);
  font-size: .54rem;
  line-height: 1.25;
}
.les-runtime-service {
  min-width: 0;
  min-height: 92px;
  border-radius: 8px !important;
  padding: 9px !important;
  background: rgba(10,17,25,.46) !important;
}
@media (max-width: 1180px) {
  .diag-live-map {
    grid-template-columns: 1fr;
  }
  .diag-map-arrow {
    min-height: 18px;
    height: 18px;
  }
  .diag-map-arrow::before {
    top: 0;
    bottom: 0;
    left: 50%;
    right: auto;
    width: 2px;
    height: auto;
    transform: translateX(-50%);
  }
  .diag-map-arrow::after {
    top: auto;
    left: calc(50% - 5px);
    right: auto;
    bottom: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 7px solid rgba(110,231,183,.9);
    border-bottom: 0;
  }
  .diag-node-hub {
    min-height: 72px;
  }
  .diag-acronym-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 760px) {
  .diag-map-groups {
    grid-template-columns: 1fr;
  }
  .diag-acronym-grid {
    grid-template-columns: 1fr;
  }
}
.output-table { width:100%; border-collapse:collapse; font-size:.75rem; }
.output-table th { padding:8px 12px; background:var(--bg-mod); border-bottom:1px solid var(--border); color:var(--dim); font-weight:700; text-transform:uppercase; font-size:.6rem; letter-spacing:.4px; text-align:left; }
.output-table td { padding:7px 12px; border-bottom:1px solid var(--border); color:var(--text); vertical-align:top; }
.output-table tr:hover td { background:var(--bg-mod); }
.chat-msg-user { align-self:flex-end; background:var(--bg-mod); color:var(--text) !important; border:1px solid var(--border); border-right:3px solid var(--pauk); border-radius:6px; padding:10px 14px; max-width:80%; font-family:var(--font-chat) !important; font-size:.9rem; line-height:1.6; }
.chat-msg-ai   { align-self:flex-start; background:var(--bg-panel); color:var(--text) !important; border:1px solid var(--border); border-left:3px solid var(--accent); border-radius:6px; padding:10px 14px; max-width:85%; font-family:var(--font-chat) !important; font-size:.9rem; line-height:1.6; }
.chat-msg-sys  { align-self:center; color:var(--dim); font-size:.72rem; border:1px solid var(--border); border-radius:4px; padding:4px 12px; font-family:var(--font-chat); }
.chat-msg-error { color:var(--err) !important; border-color:var(--err) !important; }
.sov-chat-message-text { white-space:pre-wrap; overflow-wrap:break-word; word-break:normal; }
.msg-srcs { display:flex; flex-wrap:wrap; gap:4px; margin-top:8px; }
.sov-chat-shell {
  position: relative;
  width: 100%;
  height: calc(100vh - 92px);
  min-height: 620px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 8px var(--sov-artifacts-w, 360px);
  gap: 14px;
  padding: 14px;
  background: var(--shell-bg);
  overflow: hidden;
}
.sov-chat-shell.sov-artifacts-collapsed {
  grid-template-columns: minmax(0, 1fr);
}
/* Резиновый layout: разделитель между чатом и артефактами — таскать по ширине */
.sov-resize-divider {
  cursor: col-resize;
  align-self: stretch;
  position: relative;
  touch-action: none;
}
.sov-resize-divider::before {
  content: ""; position: absolute; left: 50%; top: 50%;
  transform: translate(-50%, -50%);
  width: 4px; height: 46px; border-radius: 3px;
  background: rgba(138,162,184,.4); transition: background .15s, height .15s;
}
.sov-resize-divider:hover::before { background: var(--accent); height: 80px; }
.sov-chat-main, .sov-artifacts-panel, .sov-history-drawer {
  background: var(--panel-glass);
  border: 1px solid rgba(138,162,184,.32);
  box-shadow: var(--shadow-strong);
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
  background: var(--panel-top);
}
.sov-chat-title { color: var(--text); font-size: .92rem; font-weight: 900; letter-spacing: .08em; }
.sov-chat-subtitle { color: var(--dim); font-size: .68rem; }
.sov-chat-scroll {
  flex: 1;
  min-height: 0;
  background: var(--scroll-bg);
}
.sov-chat-thread {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  min-height: 100%;
  gap: 13px;
  padding: 22px 24px 150px;
}
/* FIX «красота не лезет»: QScrollArea-контент рос по самому широкому ребёнку (таблица/код/длинный
   токен) → бабблы (flex-start/flex-end) уезжали за оба края колонки. Держим контент = ширине окна,
   широкие блоки скроллим внутри баббла, длинные токены/кириллицу переносим. */
.sov-chat-scroll .q-scrollarea__content { width: 100% !important; max-width: 100% !important; }
.chat-msg-user, .chat-msg-ai { min-width: 0; overflow-wrap: break-word; word-break: normal; }
.chat-msg-ai table, .chat-msg-ai pre,
.sov-chat-message-text table, .sov-chat-message-text pre { display: block; max-width: 100%; overflow-x: auto; }
.chat-msg-ai img, .sov-chat-message-text img { max-width: 100%; height: auto; }
.sov-composer {
  margin: 0 18px 18px;
  padding: 10px;
  border: 1px solid rgba(138,162,184,.32);
  border-radius: 8px;
  background: var(--composer-bg);
  box-shadow: var(--shadow-strong);
}
.sov-composer-input {
  width: 100%;
  color: var(--text);
  font-family: var(--font-chat) !important;
  font-size: .92rem;
  font-weight: 650;
}
.sov-attachment-strip {
  width: 100%;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(52,211,153,.12);
  box-shadow: inset 0 0 0 1px rgba(16,185,129,.45);
}
.sov-attachment-icon {
  color: var(--accent);
  font-size: 1.1rem;
  flex: 0 0 auto;
}
.sov-attachment-copy {
  flex: 1;
  min-width: 0;
  gap: 0 !important;
}
.sov-attachment-title {
  color: var(--text);
  font-size: .72rem;
  font-weight: 900;
  line-height: 1.2;
}
.sov-attachment-chip {
  min-width: 0;
  color: var(--accent);
  font-size: .66rem;
  font-weight: 800;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.sov-composer-actions {
  width: 100%;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
}
.sov-response-settings-btn,
.sov-artifacts-open-btn {
  min-height: 34px !important;
  border: 1px solid rgba(138,162,184,.32) !important;
  border-radius: 8px !important;
  color: var(--dim) !important;
  background: transparent !important;
  font-size: .66rem !important;
  font-weight: 850 !important;
}
.sov-response-settings-menu {
  min-width: 230px;
  padding: 10px;
  background: var(--bg-panel) !important;
  border: 1px solid var(--border);
}
.sov-response-length-select { width: 100%; margin-top: 8px; }
.sov-guard-controls {
  margin-right: auto;
  align-items: center;
  gap: 8px;
  min-width: 150px;
}
.sov-guard-controls .q-toggle__label {
  color: var(--dim);
  font-size: .68rem;
  font-weight: 900;
  letter-spacing: .04em;
}
.sov-composer-actions .q-btn:last-child {
  background: linear-gradient(135deg, rgba(52,211,153,.95), rgba(34,224,111,.86)) !important;
  color: #041014 !important;
  font-weight: 900;
}
.sov-icon-btn { color: var(--dim) !important; }
.sov-new-chat-btn {
  min-height: 40px !important;
  padding: 4px 11px !important;
  border: 1px solid rgba(138,162,184,.32) !important;
  border-radius: 8px !important;
  color: var(--accent) !important;
  background: rgba(52,211,153,.08) !important;
  font-size: .66rem !important;
  font-weight: 900 !important;
}
.sov-chip {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 9px;
  border-radius: 4px;
  border: 1px solid rgba(52,211,153,.36);
  color: var(--accent);
  background: rgba(52,211,153,.10);
  font-size: .62rem;
  font-weight: 900;
}
.sov-indexing-banner {
  margin: 0 18px 10px;
  padding: 9px 12px;
  border-radius: 6px;
  border: 1px solid rgba(245,158,11,.46);
  background: rgba(245,158,11,.13);
  color: var(--warn);
  font-size: .72rem;
  font-weight: 900;
  letter-spacing: .02em;
}
.sov-composer-blocked {
  opacity: .72;
  filter: saturate(.75);
}
.sov-chip-soft {
  border-color: rgba(192,132,252,.32);
  color: var(--pauk);
  background: rgba(192,132,252,.10);
}
.sov-chip-warn {
  border-color: rgba(245,158,11,.50);
  color: var(--warn);
  background: rgba(245,158,11,.12);
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
.sov-status-pill {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 3px 9px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: color-mix(in srgb, var(--panel) 88%, var(--accent) 12%);
  color: var(--fg);
  font-size: .66rem;
  font-weight: 750;
  font-variant-numeric: tabular-nums;
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
  background: var(--artifact-bg);
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
  background: var(--card-bg) !important;
  border: 1px solid rgba(138,162,184,.32) !important;
  border-radius: 8px !important;
  box-shadow: none !important;
  gap: 12px;
}
.sov-embedded-file-viewer {
  width: 100%;
  min-height: 520px;
  overflow: hidden;
  border: 1px solid rgba(138,162,184,.32);
  border-radius: 7px;
  background: #eef3f7;
  box-shadow: 0 10px 28px rgba(3,10,18,.09);
}
.sov-embedded-file-viewer iframe {
  display: block;
  width: 100%;
  height: min(68vh, 760px);
  min-height: 520px;
  border: 0;
  background: #eef3f7;
}
@media (max-width: 700px) {
  .sov-embedded-file-viewer,
  .sov-embedded-file-viewer iframe { min-height: 440px; }
  .sov-embedded-file-viewer iframe { height: 62vh; }
}
.sov-artifact-markdown {
  color: var(--text);
  font-size: .82rem;
  line-height: 1.6;
}
.sov-artifact-table {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  table-layout: fixed;
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

/* Богатые формы прямо в пузыре чата: таблицы, mermaid-диаграммы, проза-сегменты. */
.sov-chat-rich { align-items: stretch; }
.sov-chat-md { white-space: normal; }
.sov-chat-md p { margin: .2rem 0; }
.sov-chat-inline-table {
  width: max-content;
  min-width: 100%;
  max-width: none;
  table-layout: auto;
  background: var(--bg-panel);
  color: var(--text);
  font-size: .76rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}
.sov-table-scroll {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  border-radius: 6px;
}
.sov-table-scroll .q-table__container {
  min-width: 0;
  width: 100%;
  max-width: 100%;
}
.sov-table-scroll .q-table__middle {
  overflow-x: auto !important;
}
.sov-table-scroll .q-table {
  table-layout: auto;
  min-width: max-content;
  max-width: none;
}
.sov-table-scroll .q-table__bottom { display: none !important; }
.sov-chat-inline-table td, .sov-chat-inline-table th,
.sov-artifact-table td, .sov-artifact-table th {
  min-width: 140px;
  max-width: 420px;
  white-space: normal !important;
  overflow-wrap: break-word;
  word-break: normal;
  vertical-align: top;
}
.sov-chat-inline-table th:first-child,
.sov-chat-inline-table td:first-child {
  min-width: 220px;
}
.sov-chat-inline-table thead th { font-weight: 800; }
.sov-chat-inline-mermaid {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px;
  overflow: auto;
}
.sov-chat-inline-mermaid svg { max-width: 100%; height: auto; }

/* Структурный реестр файлов в панели артефакта. */
.sov-inventory-files {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sov-inventory-file-row {
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 8px 10px;
  border: 1px solid rgba(138,162,184,.26);
  border-radius: 8px;
  background: var(--artifact-bg);
}
.sov-inventory-file-main {
  min-width: 0;
  gap: 2px;
}
.sov-inventory-file-name {
  color: var(--text);
  font-size: .74rem;
  font-weight: 800;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.sov-inventory-file-folder {
  color: var(--dim);
  font-size: .62rem;
  line-height: 1.3;
  overflow-wrap: anywhere;
}
.sov-inventory-file-role {
  color: var(--accent);
  font-size: .62rem;
  line-height: 1.3;
  font-weight: 800;
  overflow-wrap: anywhere;
}
.sov-inventory-file-meta {
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  flex-wrap: wrap;
}
.sov-inventory-status,
.sov-inventory-chunks,
.sov-inventory-layer {
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 2px 7px;
  font-size: .58rem;
  font-weight: 900;
  white-space: nowrap;
}
.sov-inventory-status-indexed { color: var(--ok); border-color: rgba(46,204,113,.4); }
.sov-inventory-status-pending { color: #d6a400; border-color: rgba(214,164,0,.42); }
.sov-inventory-status-error { color: var(--err); border-color: rgba(255,77,109,.45); }
.sov-inventory-status-unknown,
.sov-inventory-chunks { color: var(--dim); }
.sov-inventory-layer {
  color: var(--accent);
  border-color: rgba(31,145,201,.34);
  background: rgba(31,145,201,.08);
}
.sov-inventory-ask-btn {
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--accent);
  font-size: .64rem;
  font-weight: 800;
}
.sov-scope-files-panel {
  margin: 0 12px 8px;
  padding: 8px 10px;
  border: 1px solid rgba(138,162,184,.26);
  border-radius: 8px;
  background: var(--artifact-bg);
}
.sov-scope-files-head {
  width: 100%;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.sov-scope-files-icon { color: var(--accent); font-size: 1rem; }
.sov-scope-files-title {
  font-size: .68rem;
  font-weight: 900;
  color: var(--text);
  text-transform: uppercase;
  letter-spacing: .04em;
}
.sov-scope-files-note {
  font-size: .62rem;
  color: var(--dim);
  margin-left: auto;
}
.sov-scope-files-list {
  width: 100%;
  gap: 8px;
  overflow-x: auto;
  flex-wrap: nowrap;
  padding-bottom: 2px;
}
.sov-scope-file-chip {
  flex: 0 0 230px;
  min-height: 82px;
  border: 1px solid rgba(138,162,184,.28);
  border-radius: 8px;
  background: var(--card-bg);
  padding: 8px 34px 8px 10px;
  position: relative;
}
.sov-scope-file-name {
  color: var(--text);
  font-size: .68rem;
  font-weight: 800;
  line-height: 1.25;
  max-height: 2.5em;
  overflow: hidden;
  word-break: break-word;
}
.sov-scope-file-dataset {
  color: var(--dim);
  font-size: .56rem;
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sov-scope-file-badges {
  gap: 4px;
  margin-top: 6px;
  flex-wrap: wrap;
}
.sov-scope-file-badge {
  color: var(--accent);
  border: 1px solid rgba(31,145,201,.30);
  border-radius: 999px;
  background: rgba(31,145,201,.07);
  padding: 1px 6px;
  font-size: .53rem;
  font-weight: 900;
  white-space: nowrap;
}
.sov-scope-file-ask {
  position: absolute;
  right: 6px;
  top: 6px;
  color: var(--accent);
}

/* Панель «Файлы»: готовые документы-артефакты (смета xlsx, формы). */
.sov-files-artifacts {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}
.sov-file-card {
  width: 100%;
  background: var(--card-bg) !important;
  border: 1px solid rgba(138,162,184,.32) !important;
  border-radius: 8px !important;
  box-shadow: none !important;
  padding: 8px 10px !important;
}
.sov-file-icon { color: var(--accent); font-size: 1.1rem; }
.sov-smeta-approval {
  width: 100%; padding: .65rem .75rem; gap: .45rem;
  border: 1px solid color-mix(in srgb, var(--warn) 45%, var(--border));
  background: color-mix(in srgb, var(--warn) 7%, var(--bg-panel));
  box-shadow: none;
}
.sov-smeta-approval-badge {
  width: max-content; padding: .12rem .45rem; border-radius: 999px;
  color: var(--warn); background: color-mix(in srgb, var(--warn) 12%, transparent);
  font-size: .66rem; font-weight: 700; letter-spacing: .02em;
}
.sov-file-name { color: var(--text); font-weight: 700; }
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
  background: var(--artifact-bg);
  cursor: pointer;
}
.sov-session-card:hover, .sov-session-card-active {
  border-color: rgba(52,211,153,.7);
  background: rgba(52,211,153,.10);
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
  background: var(--panel-glass) !important;
  border: 1px solid rgba(138,162,184,.34) !important;
  border-radius: 8px !important;
  color: var(--text);
}
.sov-advanced-scroll {
  width: 100%;
  max-height: calc(100vh - 210px);
}
.sov-control-card {
  background: var(--artifact-bg) !important;
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
  border-color: rgba(52,211,153,.8) !important;
  color: var(--accent) !important;
  background: rgba(52,211,153,.12) !important;
}
.sov-template-preview,
.sov-prompt-preview {
  width: 100%;
  max-height: 160px;
  overflow: auto;
  border: 1px solid rgba(138,162,184,.28);
  border-radius: 8px;
  background: var(--input-bg);
  padding: 10px;
}
.sov-template-preview pre,
.sov-prompt-preview pre {
  margin: 0;
  color: var(--dim);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
  font-size: .68rem;
}
.sov-prompt-registry {
  max-height: none;
  overflow-x: hidden;
}
.sov-prompt-registry pre,
.sov-prompt-registry code {
  white-space: pre-wrap !important;
  overflow-wrap: anywhere !important;
  word-break: break-word !important;
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
.sov-live-log {
  width: 100%;
  max-height: 260px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--input-bg);
  padding: 10px 12px;
  color: var(--text);
}
.sov-live-log pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font);
  font-size: .68rem;
  line-height: 1.45;
  font-weight: 650;
}
@media (max-width: 980px) {
  .les-fuse-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
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
.src-tag-warn { border-color:var(--warn); color:var(--warn); }
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
.q-menu,
.q-dialog__inner > .q-card,
.q-dialog .q-card,
.q-list,
.q-virtual-scroll__content {
  background: var(--bg-panel) !important;
  color: var(--text) !important;
  border-color: var(--border) !important;
}
.q-item  {
  color: var(--text) !important;
  background: transparent !important;
}
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
.q-tab--active { color: var(--accent) !important; background: rgba(52,211,153,.10) !important; }
.les-top-tabs .q-tabs__content {
  height: 56px !important;
}
.les-top-tabs .q-tab {
  height: 56px !important;
  min-height: 56px !important;
  padding: 0 14px !important;
}
.les-top-tabs .q-tab__content {
  height: 56px !important;
  min-width: 0 !important;
  padding: 0 !important;
  justify-content: center !important;
  gap: 2px !important;
}
.les-top-tabs .q-tab__icon {
  font-size: 23px !important;
  margin-bottom: 0 !important;
}
.les-top-tabs .q-tab__label {
  font-size: .62rem !important;
  line-height: 1.05 !important;
  max-width: 112px !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
  white-space: nowrap !important;
}
/* Generic text */
.q-card, .q-card__section {
  background: var(--bg-panel) !important;
  color: var(--text) !important;
}
.q-field__control {
  background: var(--input-bg) !important;
}
.q-placeholder::placeholder,
textarea::placeholder,
input::placeholder {
  color: var(--dim) !important;
  opacity: .78 !important;
}
.q-table,
.q-table__container,
.q-table__middle,
.q-table thead,
.q-table tbody {
  background: var(--bg-panel) !important;
  color: var(--text) !important;
}
.q-table th {
  color: var(--dim) !important;
  font-weight: 900 !important;
}
.q-table td {
  color: var(--text) !important;
}
/* ─── Доступность (WCAG) ─────────────────────────────────────────── */
/* 2.4.7 Focus Visible: явный фокус-индикатор для клавиатуры. Только
   :focus-visible — мышиный клик контур не показывает, разметку не двигает. */
a:focus-visible,
button:focus-visible,
[tabindex]:focus-visible,
[role="button"]:focus-visible,
.q-btn:focus-visible,
.q-tab:focus-visible,
.q-toggle:focus-visible,
.q-checkbox:focus-visible,
input:focus-visible,
textarea:focus-visible,
select:focus-visible,
.q-field__native:focus-visible,
.sov-session-card:focus-visible,
.sov-format-btn:focus-visible,
.les-map-preset:focus-visible,
.mode-rag:focus-visible,
.mode-code:focus-visible {
  outline: 2px solid var(--accent) !important;
  outline-offset: 2px !important;
  border-radius: 4px;
}
/* Контраст самого индикатора фокуса на тёмном фоне — двойная обводка. */
.q-btn:focus-visible,
.q-tab:focus-visible {
  box-shadow: 0 0 0 2px var(--bg), 0 0 0 4px var(--accent) !important;
}
/* 2.3.3 Animation from Interactions: уважать prefers-reduced-motion. */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .001ms !important;
    scroll-behavior: auto !important;
  }
}

/* ═══ FEEL-BETTER PASS v0.1 — «details that make interfaces feel better» ═══════════════ */
/* Невидимый полиш: чёткость, ритм, тактильность. Терминальную эстетику не трогаем.       */

/* 1. Сглаживание шрифта — моноширинный текст чётче на тёмном фоне. */
body, .nicegui-content {
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-rendering: optimizeLegibility;
}

/* 2. ТАБЛИЧНЫЕ ЦИФРЫ — числа в таблицах/KPI/счётчиках не «прыгают» по ширине колонок.
      Главный рычаг для data-плотного интерфейса (датасеты, объёмы, диагностика). */
.kpi-val, .les-fuse-val, .les-fuse-detail,
.output-table td, .output-table th,
.q-table td, .q-table th,
.sov-chat-inline-table td, .sov-chat-inline-table th,
.diag-node-sub, .diag-node-state, .sov-session-meta, .sov-chip {
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}

/* 3. ПЛАВНОСТЬ СОСТОЯНИЙ — hover/active/focus мягкие, не мгновенные. */
.q-btn, .q-tab, .mode-rag, .mode-code, .sov-format-btn, .les-map-preset,
.card-les, .les-fuse, .diag-node, .diag-acronym-item, .sov-session-card,
.kpi-box, .q-field__control, .sov-chip, .les-runtime-service {
  transition: background-color .16s ease, border-color .16s ease,
              box-shadow .16s ease, transform .12s ease, filter .16s ease;
}

/* 4. КНОПКИ — тактильность: лёгкая подсветка на наведении, «вдавливание» на нажатии. */
.q-btn:hover:not(:disabled) { filter: brightness(1.08); }
.q-btn:active:not(:disabled) { transform: translateY(1px); }

/* 5. КАРТОЧКИ/ПРЕДОХРАНИТЕЛИ/УЗЛЫ — лёгкий подъём при наведении (без дрожи слоя). */
.card-les:hover, .les-fuse:hover, .kpi-box:hover,
.diag-node:hover, .diag-acronym-item:hover, .les-runtime-service:hover {
  border-color: rgba(52,211,153,.46);
  box-shadow: 0 4px 18px rgba(0,0,0,.28), inset 0 1px 0 rgba(255,255,255,.05);
}

/* 6. ПОЛЯ ВВОДА — мягкое фокус-кольцо акцентом (дополняет focus-visible). */
.q-field--focused .q-field__control {
  border-color: rgba(52,211,153,.7) !important;
  box-shadow: 0 0 0 3px rgba(52,211,153,.14);
}

/* 7. СТРОКИ ТАБЛИЦ — наведение читается мягче, выделяет текущую строку. */
.q-table tbody tr { transition: background-color .14s ease; }
.q-table tbody tr:hover td { background: var(--bg-mod) !important; }

/* ═══ EVIDENCE UI v0.16 — статус-полоска, бейджи, source-chips, проза ═══════════════════ */

/* Проза ответа — читаемый sans (моноширинный оставляем кодам/таблицам/числам). */
:root { --font-prose: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue',
        'Inter', system-ui, sans-serif; }
.sov-chat-md, .sov-chat-message-text, .sov-artifact-markdown {
  font-family: var(--font-prose) !important;
  line-height: 1.55;
}
.sov-chat-md code, .sov-chat-message-text code { font-family: var(--font) !important; }
.sov-chat-md h1,
.sov-chat-md h2,
.sov-chat-md h3,
.sov-chat-md h4,
.sov-chat-md h5,
.sov-chat-md h6 {
  margin: 10px 0 6px;
  font-size: .92rem;
  line-height: 1.28;
  font-weight: 800;
  letter-spacing: 0;
  text-wrap: balance;
}
.sov-chat-md h1:first-child,
.sov-chat-md h2:first-child,
.sov-chat-md h3:first-child { margin-top: 0; }
.sov-chat-md p { text-wrap: pretty; }
.sov-chat-md table, .sov-artifact-markdown table {
  display: block;
  max-width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
}
.sov-chat-md th, .sov-chat-md td,
.sov-artifact-markdown th, .sov-artifact-markdown td {
  min-width: 84px;
  max-width: 360px;
  white-space: normal;
  overflow-wrap: break-word;
  word-break: normal;
  vertical-align: top;
}
.sov-chat-md blockquote, .sov-artifact-markdown blockquote {
  margin: 8px 0 10px;
  padding: 7px 10px 7px 12px;
  border-left: 3px solid var(--accent);
  border-radius: 6px;
  background: color-mix(in srgb, var(--accent) 9%, transparent);
  color: var(--text-dim);
  font-family: var(--font);
  font-size: .76rem;
}
.sov-chat-md blockquote p, .sov-artifact-markdown blockquote p {
  margin: 0;
}

/* Статус-полоска ответа: статус + бейджи evidence + источники + intent. */
.sov-ev-header {
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0 0 9px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(138,162,184,.18);
}
.sov-ev-status {
  font-family: var(--font);
  font-size: .6rem;
  font-weight: 900;
  letter-spacing: .06em;
  padding: 2px 9px;
  border-radius: 5px;
  border: 1px solid currentColor;
}
.sov-ev-badge {
  font-family: var(--font);
  font-size: .56rem;
  font-weight: 800;
  letter-spacing: .04em;
  padding: 2px 7px;
  border-radius: 5px;
  border: 1px solid color-mix(in srgb, currentColor 42%, transparent);
  background: color-mix(in srgb, currentColor 10%, transparent);
}
.sov-ev-meta { color: var(--dim); font-size: .62rem; font-family: var(--font); }
/* Сдержанные семантические тона (не неон). */
.sov-ev-ok   { color: var(--ok); }
.sov-ev-acc  { color: var(--accent); }
.sov-ev-warn { color: var(--warn); }
.sov-ev-err  { color: var(--err); }
.sov-ev-dim  { color: var(--dim); }
.sov-ev-status.sov-ev-ok  { background: rgba(34,224,111,.10); }
.sov-ev-status.sov-ev-warn{ background: rgba(255,209,102,.10); }
.sov-ev-status.sov-ev-err { background: rgba(255,107,107,.11); }
.sov-ev-status.sov-ev-dim { background: rgba(138,162,184,.10); }

/* Trace — компактный, свёрнут по умолчанию. */
.sov-ev-trace { margin-top: 8px; }
.sov-ev-trace .q-expansion-item__label { font-size: .62rem; color: var(--dim); }
.sov-ev-trace-text { font-family: var(--font); font-size: .6rem; color: var(--dim); line-height: 1.5; }

/* Source-chips: «N · file · абз.85» — кликабельный вид, моноширинный локатор. */
.src-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--font);
  font-size: .58rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 5px;
  border: 1px solid rgba(34,224,111,.45);
  color: var(--ok);
  background: rgba(34,224,111,.07);
  cursor: default;
  transition: background-color .14s ease, border-color .14s ease;
}
.src-tag:hover { background: rgba(34,224,111,.14); border-color: rgba(34,224,111,.7); }

/* Источники ответа: закрыты по умолчанию; даже раскрытый длинный список не растягивает ленту. */
.sov-source-expansion {
  width: 100%;
  margin-top: 8px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--bg-mod) 72%, transparent);
  box-shadow: inset 0 0 0 1px rgba(28, 44, 64, .10);
  overflow: hidden;
}
.sov-source-expansion > .q-expansion-item__container > .q-item {
  min-height: 40px;
  padding: 5px 10px;
  color: var(--dim);
}
.sov-source-expansion .q-expansion-item__label {
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}
.sov-source-expansion .q-expansion-item__toggle-icon {
  transition-property: transform;
  transition-duration: .18s;
  transition-timing-function: cubic-bezier(.2, 0, 0, 1);
}
.sov-source-list {
  width: 100%;
  max-height: min(42vh, 360px);
  gap: 2px !important;
  padding: 4px 7px 8px;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.sov-source-row {
  width: 100%;
  min-height: 40px;
  align-items: center;
  gap: 7px;
  margin: 0;
  padding: 4px 5px 4px 9px;
  border-radius: 9px;
  transition-property: background-color, box-shadow;
  transition-duration: .14s;
  transition-timing-function: ease;
}
.sov-source-row:hover {
  background: color-mix(in srgb, var(--accent) 7%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 16%, transparent);
}
.sov-source-primary {
  min-width: 0;
  min-height: 40px !important;
  flex: 1 1 220px;
  justify-content: flex-start;
  color: var(--text) !important;
  font-family: var(--font-ui);
  font-size: 12px !important;
  font-weight: 750;
  line-height: 1.35;
  text-align: left;
  text-decoration: none;
  overflow-wrap: anywhere;
  transition-property: color, scale;
  transition-duration: .14s;
  transition-timing-function: ease;
}
.sov-source-primary:hover { color: var(--accent) !important; }
.sov-source-primary:active { scale: .96; }
.sov-source-unavailable { color: var(--dim) !important; }
.sov-source-kind {
  flex: 0 0 auto;
  color: var(--ok);
  font-family: var(--font-ui);
  font-size: 11px !important;
  font-weight: 750;
}
.sov-source-kind-warn { color: var(--warn); }
.sov-source-detail {
  flex: 0 0 40px;
  width: 40px;
  min-width: 40px !important;
  min-height: 40px !important;
  color: var(--dim) !important;
  transition-property: color, background-color, scale;
  transition-duration: .14s;
  transition-timing-function: ease;
}
.sov-source-detail:hover {
  color: var(--accent) !important;
  background: color-mix(in srgb, var(--accent) 9%, transparent) !important;
}
.sov-source-detail:active { scale: .96; }
.sov-source-tools:empty { display: none; }

/* Inline-таблица в чате: читаемее, не «терминал». */
.sov-chat-inline-table { font-family: var(--font); font-size: .74rem; }
.sov-chat-inline-table thead th {
  position: sticky; top: 0;
  background: var(--bg-mod) !important;
  font-weight: 800; letter-spacing: .02em;
}
.sov-chat-inline-table td, .sov-chat-inline-table th { font-variant-numeric: tabular-nums; }

/* v0.20 — действия ответа (Копировать), плашка модели, меню примеров. */
.sov-answer-actions { opacity: .55; transition: opacity .14s ease; }
.chat-msg-ai:hover .sov-answer-actions { opacity: 1; }
.sov-answer-act {
  color: var(--dim) !important;
  font-size: .58rem !important;
  font-family: var(--font);
  padding: 1px 7px !important;
  min-height: 0 !important;
}
.sov-answer-act:hover { color: var(--accent) !important; }
.sov-model-chip {
  max-width: 280px;
  font-family: var(--font-ui);
  white-space: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
}
.sov-model-badge {
  align-self: flex-start;
  width: fit-content;
  max-width: 100%;
  margin: 0;
  padding: 2px 8px;
  border: 1px solid rgba(28, 44, 64, .16);
  border-radius: 999px;
  background: rgba(255,255,255,.62);
  color: var(--dim);
  font-family: var(--font-ui);
  font-size: 11.5px !important;
  font-weight: 800;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.sov-answer-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
  margin: 0 0 4px;
  max-width: 100%;
}
.sov-chat-timing {
  color: var(--dim);
  font-family: var(--font-ui);
  font-size: 11px !important;
  font-weight: 600;
  line-height: 1.35;
  letter-spacing: .01em;
  white-space: nowrap;
}
.sov-chat-timing--user {
  align-self: flex-end;
  margin: 0 0 2px;
  opacity: .85;
}
.sov-prompt-editor {
  width: 100%;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(255,255,255,.42);
}
.sov-prompt-textarea textarea {
  font-family: var(--font);
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.sov-examples-menu .q-item { min-height: 0; padding: 3px 12px; }

/* ═══ v0.24 UI-РЕФРЕШ · Этап 1 — читаемость + де-терминал хрома (аддитивно, обратимо) ═══════ */
/* Хром (шапка/табы/лейблы/чипы/действия) → чистый sans вместо моно, размеры ≥12px.            */
/* Данные (таблицы/логи/числа/коды) остаются моноширинными. Плотные диаг-сетки не трогаем.      */
:root {
  --font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', system-ui, sans-serif;
  --fs-xs: 12px;
  --fs-sm: 13px;
}
.les-top-tabs .q-tab__label {
  font-family: var(--font-ui) !important;
  font-size: var(--fs-sm) !important;
  max-width: 200px !important;
  letter-spacing: 0 !important;
  line-height: 1.1 !important;
}
.les-top-tabs .q-tab__icon { font-size: 20px !important; }
.les-brand { font-family: var(--font-ui) !important; text-shadow: none !important; }
.q-btn__content, .q-item__label, .q-field__label, .q-tab__label,
.sov-panel-title, .section-title, .sov-chat-title, .sov-chat-subtitle,
.sov-session-title, .sov-tree-name, .sov-answer-act {
  font-family: var(--font-ui) !important;
}
.src-tag, .sov-chip, .sov-ev-status, .sov-answer-act,
.sov-ev-meta, .sov-chat-subtitle, .sov-session-meta, .sov-muted {
  font-size: var(--fs-xs) !important;
}
.sov-ev-badge { font-size: 11.5px !important; }
.src-tag i { font-size: 14px !important; }
/* Этап 4 — чат: бабблы круглее/крупнее, чипы-источники как пилюли, подсказка композера. */
.chat-msg-user, .chat-msg-ai {
  border-radius: 12px !important;
  padding: 11px 15px !important;
  font-size: 14px !important;
  line-height: 1.6 !important;
}
.chat-msg-user { background: var(--bg-mod) !important; border-right: 1px solid var(--border) !important; }
.chat-msg-ai { border-left: 2px solid var(--accent) !important; }
.src-tag { border-radius: 7px !important; padding: 3px 9px !important; }
.sov-composer { border-radius: 12px !important; }
.sov-composer-hint {
  color: var(--dim);
  font-size: 11.5px;
  font-family: var(--font-ui);
  padding: 2px 4px 0;
  opacity: .82;
}

/* ═══ Chat UI — спокойный первый слой + контекстные подсказки режимов ═══════════════ */
.sov-chat-heading {
  gap: 0 !important;
  min-width: 0;
}
.sov-chat-topbar .sov-icon-btn,
.sov-scope-btn {
  min-width: 40px !important;
  min-height: 40px !important;
}
.sov-scope-btn {
  max-width: 280px;
  padding: 6px 12px !important;
  border-radius: 10px !important;
  color: var(--accent) !important;
  background: rgba(52,211,153,.08) !important;
  box-shadow: 0 0 0 1px rgba(52,211,153,.24);
  font-family: var(--font-ui) !important;
  font-size: 12px !important;
  font-weight: 800 !important;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sov-chat-empty {
  align-self: center;
  width: min(100%, 560px);
  margin: auto;
  padding: 28px 24px;
  border-radius: 18px;
  background: color-mix(in srgb, var(--bg-panel) 72%, transparent);
  box-shadow:
    0 0 0 1px rgba(138,162,184,.18),
    0 12px 36px rgba(0,0,0,.08);
  text-align: center;
  font-family: var(--font-ui);
}
.sov-chat-empty-title {
  color: var(--text);
  font-size: 20px;
  font-weight: 850;
  line-height: 1.2;
  text-wrap: balance;
}
.sov-chat-empty-copy {
  margin-top: 7px;
  color: var(--dim);
  font-size: 13px;
  line-height: 1.45;
  text-wrap: pretty;
}
.sov-chat-thread {
  width: min(calc(100% - 48px), 1440px) !important;
  margin-inline: auto;
}
.sov-composer {
  align-self: center;
  position: relative;
  width: calc(100% - 48px);
  max-width: 1440px;
  padding: 8px 10px !important;
  border: 0 !important;
  border-radius: 18px !important;
  box-shadow:
    0 0 0 1px rgba(138,162,184,.24),
    0 12px 36px rgba(0,0,0,.14) !important;
}
.sov-composer-input .q-field__control,
.sov-composer-input .q-field__native {
  min-height: 34px !important;
}
.sov-composer-input .q-field__native {
  max-height: 112px;
  padding: 5px 2px !important;
  line-height: 1.35;
  overflow-y: auto !important;
}
.sov-mode-picker {
  width: 100%;
  align-items: center;
  gap: 6px;
  margin: 2px 0 0;
  padding-right: 420px;
  flex-wrap: nowrap;
}
.sov-mode-btn {
  min-height: 40px !important;
  padding: 7px 12px !important;
  border-radius: 10px !important;
  font-family: var(--font-ui) !important;
  font-size: 12px !important;
  font-weight: 800 !important;
  transition-property: scale, background-color, border-color, color, box-shadow !important;
  transition-duration: 150ms !important;
  transition-timing-function: cubic-bezier(.2, 0, 0, 1) !important;
}
.sov-mode-guides {
  position: absolute;
  z-index: 8;
  left: 10px;
  bottom: calc(100% + 10px);
  width: min(calc(100% - 20px), 900px);
  pointer-events: none;
}
.sov-mode-guide {
  width: 100%;
  padding: 8px 9px;
  border-radius: 11px;
  background: color-mix(in srgb, var(--bg-panel) 92%, transparent);
  box-shadow: 0 12px 32px rgba(0,0,0,.18), 0 0 0 1px rgba(138,162,184,.24);
  font-family: var(--font-ui);
  pointer-events: auto;
}
.sov-mode-guide-head {
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
}
.sov-mode-guide-title {
  color: var(--dim);
  font-size: 11px;
  font-weight: 850;
}
.sov-mode-guide-copy {
  display: none;
}
.sov-mode-data-hint {
  display: none;
}
.sov-mode-examples {
  width: 100%;
  gap: 5px;
  margin-top: 4px;
  min-height: 0;
  padding-right: 0;
  align-items: center;
  flex-wrap: wrap;
}
.sov-mode-example {
  min-height: 30px !important;
  padding: 4px 8px !important;
  border-radius: 8px !important;
  color: var(--text) !important;
  background: color-mix(in srgb, var(--bg-panel) 72%, transparent) !important;
  box-shadow: 0 0 0 1px rgba(138,162,184,.18);
  font-family: var(--font-ui) !important;
  font-size: 11px !important;
  font-weight: 700 !important;
  transition-property: scale, background-color, box-shadow !important;
  transition-duration: 150ms !important;
  transition-timing-function: cubic-bezier(.2, 0, 0, 1) !important;
}
.sov-mode-example:hover {
  background: color-mix(in srgb, var(--bg-panel) 84%, var(--accent) 16%) !important;
  box-shadow: 0 0 0 1px rgba(52,211,153,.32);
}
.sov-composer-footer {
  position: absolute;
  right: 10px;
  bottom: 8px;
  z-index: 2;
  width: auto;
  min-height: 44px;
  display: flex;
  align-items: center;
  margin: 0;
  padding: 0;
  background: transparent;
  box-shadow: none;
}
.sov-composer-actions {
  width: auto;
  margin: 0 0 0 auto;
  flex-wrap: nowrap;
}
.sov-composer-action {
  min-width: 40px !important;
  min-height: 40px !important;
  color: var(--dim) !important;
}
.sov-send-btn {
  min-height: 44px !important;
  padding-inline: 16px !important;
  border-radius: 10px !important;
  transition-property: scale, filter, box-shadow !important;
  transition-duration: 150ms !important;
}
.sov-stop-dialog-btn {
  min-height: 40px !important;
  color: var(--err) !important;
  border: 1px solid color-mix(in srgb, var(--err) 55%, transparent) !important;
  border-radius: 9px !important;
}
.sov-mode-btn:active:not(:disabled),
.sov-mode-example:active:not(:disabled),
.sov-composer-action:active:not(:disabled),
.sov-send-btn:active:not(:disabled) {
  scale: .96;
  transform: none !important;
}
@media (max-width: 1100px) {
  .sov-mode-picker { padding-right: 0; flex-wrap: wrap; }
  .sov-mode-guides { width: calc(100% - 20px); }
  .sov-composer-footer {
    position: static;
    width: 100%;
    min-height: 40px;
    margin-top: 3px;
  }
}
@media (max-width: 640px) {
  .sov-mode-guides { bottom: calc(100% + 7px); }
  .sov-mode-example { width: auto !important; min-height: 28px !important; }
}
.sov-tools-menu {
  min-width: 280px;
  padding: 10px;
  border-radius: 14px !important;
  font-family: var(--font-ui);
}
.sov-tools-title {
  padding: 4px 8px 6px;
  color: var(--text);
  font-size: 13px;
  font-weight: 850;
}
.sov-validation-control {
  width: 100%;
  min-height: 40px;
  padding: 2px 8px;
  align-items: center;
  justify-content: space-between;
}
.sov-validation-control .q-toggle__label,
.sov-validation-state {
  font-family: var(--font-ui) !important;
  font-size: 12px !important;
}
.sov-validation-state { color: var(--dim); }

/* Documents — calm, read-only common data environment */
.sov-docs-shell {
  --docs-border-strong: color-mix(in srgb, var(--text) 24%, transparent);
  --docs-border-soft: color-mix(in srgb, var(--text) 15%, transparent);
  --docs-muted-strong: color-mix(in srgb, var(--text) 78%, var(--bg-panel));
  min-height: calc(100vh - 112px);
  background:
    radial-gradient(circle at 18% 0%, rgba(52,211,153,.055), transparent 28%),
    var(--bg);
  font-family: var(--font-ui);
  -webkit-font-smoothing: antialiased;
}
.sov-docs-topbar {
  min-height: 76px;
  gap: 14px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--docs-border-strong);
  background: color-mix(in srgb, var(--bg-panel) 88%, transparent);
  backdrop-filter: blur(18px);
}
.sov-docs-heading { min-width: 230px; gap: 1px !important; }
.sov-docs-title { letter-spacing: .02em; text-wrap: balance; }
.sov-docs-subtitle {
  color: var(--docs-muted-strong) !important;
  font-weight: 600 !important;
  text-wrap: pretty;
}
.sov-docs-search {
  width: min(620px, 52vw);
  margin-left: auto;
}
.sov-docs-search .q-field__control,
.sov-docs-filter .q-field__control {
  min-height: 42px !important;
  border-radius: 12px !important;
  background: color-mix(in srgb, var(--input-bg) 92%, transparent);
}
.sov-docs-shell .q-field--outlined .q-field__control::before {
  border: 1px solid var(--docs-border-strong) !important;
}
.sov-docs-shell .q-field--outlined:hover .q-field__control::before {
  border-color: color-mix(in srgb, var(--text) 38%, transparent) !important;
}
.sov-docs-shell .q-field__native,
.sov-docs-shell .q-field__input,
.sov-docs-shell .q-field__label {
  color: var(--text) !important;
  font-weight: 600;
}
.sov-docs-shell .q-field__native::placeholder,
.sov-docs-shell .q-field__input::placeholder {
  color: var(--docs-muted-strong) !important;
  opacity: 1;
}
.sov-docs-search-btn {
  min-height: 42px !important;
  padding-inline: 16px !important;
  border-radius: 11px !important;
  color: #041014 !important;
  background: linear-gradient(135deg, rgba(52,211,153,.94), rgba(34,224,111,.82)) !important;
  font-weight: 850 !important;
  box-shadow: 0 8px 22px rgba(16,185,129,.14);
}
.sov-docs-workspace {
  min-height: 0;
  gap: 10px;
  padding: 10px;
  overflow: hidden;
}
.sov-docs-datasets-panel,
.sov-docs-files-panel,
.sov-docs-view-panel {
  min-height: 0;
  gap: 10px !important;
  overflow: hidden;
  border: 1px solid var(--docs-border-strong);
  border-radius: 16px;
  background: color-mix(in srgb, var(--bg-panel) 94%, transparent);
  box-shadow:
    0 0 0 1px rgba(138,162,184,.14),
    0 1px 2px -1px rgba(3,10,18,.12),
    0 12px 30px rgba(3,10,18,.05);
}
.sov-docs-datasets-panel {
  width: 250px;
  min-width: 230px;
  padding: 14px 12px;
}
.sov-docs-files-panel {
  width: 420px;
  min-width: 360px;
  padding: 14px 12px;
}
.sov-docs-view-panel {
  flex: 1;
  min-width: 0;
  padding: 14px 18px;
  overflow: auto;
}
.sov-docs-panel-title {
  min-height: 28px;
  gap: 7px;
  padding-inline: 4px;
  letter-spacing: .01em;
  color: var(--text);
}
.sov-docs-panel-title .q-label {
  color: var(--text) !important;
  font-weight: 850 !important;
}
.sov-docs-panel-title .q-icon { color: var(--accent); font-size: 18px; }
.sov-docs-filter { width: 100%; }
.sov-dataset-group-filter {
  width: 100%;
  gap: 2px;
  padding: 3px;
  border-radius: 11px;
  border: 1px solid var(--docs-border-soft);
  background: color-mix(in srgb, var(--bg) 72%, var(--bg-panel));
  box-shadow: inset 0 0 0 1px rgba(138,162,184,.14);
}
.sov-dataset-group-btn {
  min-height: 38px !important;
  flex: 1;
  padding-inline: 8px !important;
  border-radius: 8px !important;
  color: var(--docs-muted-strong) !important;
  font-weight: 700 !important;
}
.sov-dataset-group-btn--active {
  color: var(--text) !important;
  background: var(--bg-panel) !important;
  border: 1px solid var(--docs-border-strong) !important;
  box-shadow: 0 3px 10px rgba(3,10,18,.05);
}
.sov-docs-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 1px 2px 10px;
  scrollbar-gutter: stable;
}
.sov-dataset-card,
.sov-document-card {
  cursor: pointer;
  padding: 11px;
  border-radius: 13px;
  border: 1px solid var(--docs-border-soft);
  background: color-mix(in srgb, var(--bg-panel) 92%, var(--bg) 8%);
  box-shadow: 0 0 0 1px rgba(138,162,184,.14);
  transition-property: scale, background-color, box-shadow;
  transition-duration: 150ms;
  transition-timing-function: cubic-bezier(.2, 0, 0, 1);
}
.sov-dataset-card:hover,
.sov-document-card:hover {
  border-color: color-mix(in srgb, var(--accent) 52%, var(--docs-border-strong));
  background: color-mix(in srgb, var(--bg-panel) 86%, var(--accent) 14%);
  box-shadow: 0 0 0 1px rgba(52,211,153,.28), 0 7px 20px rgba(3,10,18,.06);
}
.sov-dataset-card--selected,
.sov-document-card--selected {
  border-color: color-mix(in srgb, var(--accent) 72%, var(--docs-border-strong));
  background: color-mix(in srgb, var(--bg-panel) 76%, var(--accent) 24%);
  box-shadow: 0 0 0 1px rgba(52,211,153,.46), 0 9px 24px rgba(16,185,129,.09);
}
.sov-dataset-card-head,
.sov-document-card-head { gap: 9px; flex-wrap: nowrap; }
.sov-dataset-icon,
.sov-document-icon,
.sov-docs-view-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  min-width: 36px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--accent) 34%, var(--docs-border-soft));
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, var(--bg-panel));
  box-shadow: inset 0 0 0 1px rgba(52,211,153,.16);
}
.sov-dataset-icon .q-icon,
.sov-document-icon .q-icon,
.sov-docs-view-icon .q-icon { font-size: 19px; }
.sov-dataset-name,
.sov-document-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-wrap: pretty;
}
.sov-dataset-name { flex: 1; }
.sov-dataset-chevron { color: var(--dim); opacity: .55; }
.sov-document-copy { min-width: 0; flex: 1; gap: 1px !important; }
.sov-doc-tree-folder {
  border: 1px solid var(--docs-border-strong);
  border-radius: 11px;
  background: color-mix(in srgb, var(--bg-panel) 96%, var(--bg));
  flex: 0 0 auto;
  overflow: hidden;
}
.sov-dataset-data-button {
  min-height: 42px;
  justify-content: flex-start;
  border: 1px solid var(--docs-border-strong);
  border-radius: 11px;
  background: color-mix(in srgb, var(--bg-panel) 94%, var(--bg));
  color: var(--text);
  font-weight: 800;
}
.sov-dataset-data-button--active {
  border-color: color-mix(in srgb, var(--accent) 72%, var(--docs-border-strong));
  background: color-mix(in srgb, var(--accent) 13%, var(--bg-panel));
  color: var(--accent);
}
.sov-document-map-filter {
  min-height: 40px;
  gap: 7px;
  padding: 5px 7px 5px 11px;
  border: 1px solid color-mix(in srgb, var(--accent) 52%, var(--docs-border-strong));
  border-radius: 10px;
  background: color-mix(in srgb, var(--accent) 9%, var(--bg-panel));
  color: var(--text);
}
.sov-document-map-filter > .q-icon { color: var(--accent); }
.sov-doc-tree-folder > .q-expansion-item__container > .q-item {
  min-height: 44px;
  color: var(--text);
  font-weight: 800;
}
.sov-doc-tree-folder .q-expansion-item__content {
  padding: 2px 6px 8px 14px;
  border-top: 1px solid var(--docs-border-soft);
  background: color-mix(in srgb, var(--bg) 24%, var(--bg-panel));
}
.sov-doc-tree-folder .sov-document-card--tree,
.sov-doc-tree-folder .sov-doc-tree-folder {
  margin-top: 6px;
}
.sov-document-card--tree {
  flex: 0 0 auto;
  padding: 8px 9px;
  border-radius: 10px;
}
.sov-document-card--tree .sov-document-meta-text,
.sov-document-card--tree .sov-document-attention {
  padding-left: 39px;
}
.sov-document-path {
  color: var(--docs-muted-strong) !important;
  font-weight: 600 !important;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sov-dataset-meta-text,
.sov-document-meta-text,
.sov-dataset-attention,
.sov-document-attention {
  display: block;
  margin-top: 5px;
  padding-left: 45px;
  line-height: 1.35;
  color: var(--docs-muted-strong) !important;
  font-weight: 600 !important;
  font-variant-numeric: tabular-nums;
  text-wrap: pretty;
}
.sov-docs-view-head {
  position: sticky;
  top: -14px;
  z-index: 4;
  gap: 10px;
  margin: -14px -18px 0;
  padding: 12px 18px 10px;
  background: color-mix(in srgb, var(--bg-panel) 92%, transparent);
  backdrop-filter: blur(18px);
  border-bottom: 1px solid var(--docs-border-strong);
}
.sov-docs-view-title { text-wrap: balance; }
.sov-docs-view-tabs {
  gap: 2px;
  padding: 3px;
  border-radius: 12px;
  border: 1px solid var(--docs-border-soft);
  background: color-mix(in srgb, var(--bg) 72%, var(--bg-panel));
  box-shadow: inset 0 0 0 1px rgba(138,162,184,.14);
}
.sov-docs-view-tab,
.sov-docs-more {
  min-height: 40px !important;
  border-radius: 9px !important;
  color: var(--docs-muted-strong) !important;
  font-weight: 700 !important;
  transition-property: scale, color, background-color, box-shadow !important;
  transition-duration: 150ms !important;
}
.sov-docs-view-tab--active {
  color: var(--text) !important;
  background: var(--bg-panel) !important;
  border: 1px solid var(--docs-border-strong) !important;
  box-shadow: 0 4px 12px rgba(3,10,18,.06);
}
.sov-docs-view-note {
  margin: 12px 2px 2px;
  color: var(--docs-muted-strong) !important;
  font-weight: 650 !important;
  text-wrap: pretty;
}
.sov-file-registry,
.sov-list-overview,
.sov-list-map,
.sov-docs-coverage,
.sov-list-root-card,
.sov-list-discipline-card,
.sov-list-file-card {
  border: 1px solid var(--docs-border-strong) !important;
  background: color-mix(in srgb, var(--bg-panel) 94%, transparent) !important;
  box-shadow: 0 0 0 1px rgba(138,162,184,.14), 0 8px 24px rgba(3,10,18,.045);
}
.sov-file-registry,
.sov-list-overview,
.sov-list-map,
.sov-docs-coverage { border-radius: 14px !important; }
.sov-file-registry .q-expansion-item__content { padding: 0 12px 12px; }
.sov-composition-summary { gap: 11px !important; padding: 4px 2px 12px; }
.sov-composition-overview {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));
  gap: 1px;
  width: 100%;
  overflow: hidden;
  border-radius: 12px;
  border: 1px solid var(--docs-border-strong);
  background: color-mix(in srgb, var(--border) 55%, transparent);
  box-shadow: 0 0 0 1px rgba(138,162,184,.08);
}
.sov-composition-stat {
  min-width: 0;
  padding: 10px 12px;
  background: var(--bg-panel);
}
.sov-composition-stat + .sov-composition-stat { border-left: 1px solid var(--docs-border-strong); }
.sov-composition-stat-value {
  letter-spacing: -.035em;
  font-variant-numeric: tabular-nums;
}
.sov-composition-stat-caption {
  margin-top: 1px;
  color: var(--docs-muted-strong) !important;
  font-weight: 650 !important;
}
.sov-composition-stat--good .sov-composition-stat-value { color: var(--accent) !important; }
.sov-composition-stat--warn .sov-composition-stat-value { color: var(--warn) !important; }
.sov-composition-stat--danger .sov-composition-stat-value { color: var(--err) !important; }
.sov-composition-type-line {
  padding-inline: 2px;
  font-variant-numeric: tabular-nums;
  letter-spacing: .01em;
  color: var(--docs-muted-strong) !important;
  font-weight: 600 !important;
}
.sov-composition-folders {
  display: grid !important;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 8px !important;
}
.sov-composition-view-switch {
  gap: 2px;
  width: fit-content;
  padding: 3px;
  border-radius: 11px;
  border: 1px solid var(--docs-border-soft);
  background: color-mix(in srgb, var(--bg) 72%, var(--bg-panel));
}
.sov-composition-view-btn {
  min-height: 38px !important;
  border-radius: 8px !important;
  color: var(--docs-muted-strong) !important;
  font-weight: 700 !important;
}
.sov-composition-view-btn--active {
  color: var(--text) !important;
  background: var(--bg-panel) !important;
  border: 1px solid var(--docs-border-strong) !important;
  box-shadow: 0 3px 10px rgba(3,10,18,.05);
}
.sov-composition-browser {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}
.sov-composition-navigation,
.sov-composition-inspector {
  min-width: 0;
  gap: 10px !important;
}
.sov-composition-inspector {
  position: static;
  max-height: none;
  overflow: visible;
  padding: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
.sov-composition-inspector-head { gap: 8px; }
.sov-composition-folder-description {
  line-height: 1.5;
  text-wrap: pretty;
}
.sov-composition-inspector-files { gap: 5px !important; }
.sov-composition-tree-node {
  border-radius: 9px;
  border: 1px solid var(--docs-border-soft);
  background: color-mix(in srgb, var(--bg-panel) 97%, transparent);
  box-shadow: inset 0 -1px 0 rgba(138,162,184,.11);
}
.sov-composition-tree-node .q-expansion-item__content { padding: 0 6px 7px 16px; }
.sov-composition-folder-summary-link {
  cursor: pointer;
  margin: -2px 4px 5px;
  padding: 4px 8px;
  border-radius: 7px;
  transition-property: background-color;
  transition-duration: 140ms;
}
.sov-composition-folder-summary-link:hover { background: color-mix(in srgb, var(--accent) 7%, transparent); }
.sov-composition-up { min-height: 36px !important; color: var(--accent) !important; }
.sov-composition-folder-list { gap: 7px !important; }
.sov-composition-file-row {
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  min-height: 42px;
  padding: 6px 7px;
  border-radius: 9px;
  border: 1px solid var(--docs-border-soft);
  background: color-mix(in srgb, var(--bg-panel) 97%, var(--bg));
  transition-property: background-color, box-shadow, scale;
  transition-duration: 140ms;
  transition-timing-function: cubic-bezier(.2, 0, 0, 1);
}
.sov-composition-file-row:hover {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--docs-border-strong));
  background: color-mix(in srgb, var(--accent) 7%, var(--bg-panel));
  box-shadow: inset 0 0 0 1px rgba(52,211,153,.12);
}
.sov-composition-file-row:active { scale: .96; }
.sov-composition-file-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  min-width: 30px;
  border-radius: 8px;
  border: 1px solid color-mix(in srgb, var(--accent) 28%, var(--docs-border-soft));
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, var(--bg-panel));
}
.sov-composition-file-copy { min-width: 0; flex: 1; gap: 0 !important; }
.sov-composition-file-name,
.sov-composition-file-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sov-composition-file-path {
  color: var(--docs-muted-strong) !important;
  font-weight: 600 !important;
}
.sov-composition-folder {
  min-width: 0;
  padding: 11px;
  border-radius: 12px;
  border: 1px solid var(--docs-border-strong);
  background: color-mix(in srgb, var(--bg-panel) 88%, var(--bg) 12%);
  box-shadow: 0 0 0 1px rgba(138,162,184,.14);
}
.sov-composition-folder-head { gap: 8px; flex-wrap: nowrap; }
.sov-composition-folder-icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  min-width: 32px;
  border-radius: 9px;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, var(--bg-panel));
}
.sov-composition-folder-name {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sov-composition-folder-count {
  color: var(--docs-muted-strong) !important;
  font-weight: 650 !important;
}
.sov-composition-samples {
  margin: 7px 0 0 40px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-wrap: pretty;
  color: var(--docs-muted-strong) !important;
  font-weight: 600 !important;
}
.sov-composition-filters {
  display: grid !important;
  grid-template-columns: minmax(220px, 1.5fr) repeat(3, minmax(130px, .75fr)) minmax(190px, 1fr);
  gap: 7px !important;
  width: 100%;
}
.sov-composition-filters > * { min-width: 0; }
.sov-file-panel-filters {
  display: grid !important;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px !important;
  padding: 2px 3px 7px;
}
.sov-file-panel-filters > * { min-width: 0; }
.sov-file-panel-filters .q-field__label,
.sov-file-panel-filters .q-field__native { font-size: 10.5px !important; }
.sov-index-quality {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--bg-panel);
  box-shadow: 0 0 0 1px rgba(138,162,184,.22), 0 8px 24px rgba(3,10,18,.04);
}
.sov-index-quality-head { gap: 8px !important; flex-wrap: wrap; }
.sov-index-quality-head .q-icon { font-size: 18px; color: var(--accent); }
.sov-index-quality-metrics {
  gap: 6px !important;
  margin-top: 9px;
  flex-wrap: wrap;
  font-variant-numeric: tabular-nums;
}
.sov-index-quality-channels { margin-top: 8px; }
.sov-index-quality-note {
  margin-top: 5px;
  text-wrap: pretty;
}
.sov-index-quality-files {
  margin-top: 9px;
  border-radius: 9px !important;
  box-shadow: inset 0 0 0 1px rgba(138,162,184,.20);
}
.sov-index-quality-file {
  margin: 4px 7px;
  border-radius: 8px !important;
  background: color-mix(in srgb, var(--bg-panel) 93%, var(--accent) 7%);
}
.sov-index-quality-sample {
  margin-top: 3px;
  line-height: 1.45;
  text-wrap: pretty;
  overflow-wrap: anywhere;
}
.sov-composition-file-row--selected {
  border-color: color-mix(in srgb, var(--accent) 72%, var(--docs-border-strong));
  background: color-mix(in srgb, var(--accent) 10%, var(--bg-panel));
  box-shadow: inset 3px 0 0 var(--accent);
}
.sov-composition-table-wrap {
  width: 100%;
  overflow: auto;
  border-radius: 11px;
  border: 1px solid var(--docs-border-strong);
  box-shadow: 0 0 0 1px rgba(138,162,184,.16);
}
.sov-composition-table {
  width: 100%;
  min-width: 900px;
  border-collapse: collapse;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.sov-composition-table th,
.sov-composition-table td {
  padding: 8px 9px;
  text-align: left;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
  vertical-align: middle;
}
.sov-composition-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  color: var(--docs-muted-strong);
  font-weight: 800;
  background: var(--bg-panel);
}
.sov-composition-table td:first-child {
  max-width: 310px;
  font-weight: 750;
  overflow-wrap: anywhere;
}
.sov-composition-table tbody tr {
  cursor: pointer;
  transition-property: background-color;
  transition-duration: 120ms;
}
.sov-composition-table tbody tr:hover { background: color-mix(in srgb, var(--accent) 6%, var(--bg-panel)); }
.sov-composition-file-loading { gap: 5px; flex-wrap: wrap; }
.sov-index-brief {
  padding: 14px;
  border-radius: 13px;
  border: 1px solid var(--docs-border-strong);
  background: var(--bg-panel);
  box-shadow: 0 0 0 1px rgba(138,162,184,.11), 0 5px 16px rgba(3,10,18,.035);
}
.sov-index-brief--dataset {
  border-color: color-mix(in srgb, var(--accent) 48%, var(--docs-border-strong));
  background: color-mix(in srgb, var(--accent) 7%, var(--bg-panel));
  box-shadow: 0 0 0 1px rgba(52,211,153,.18), 0 6px 18px rgba(16,185,129,.045);
}
.sov-index-brief--file {
  background: color-mix(in srgb, var(--bg-panel) 97%, var(--bg));
}
.sov-selected-file-dock {
  position: relative;
  margin-top: 12px;
  border-color: color-mix(in srgb, var(--accent) 58%, var(--docs-border-strong));
  background: color-mix(in srgb, var(--accent) 6%, var(--bg-panel));
  box-shadow: 0 8px 24px rgba(3,10,18,.08);
}
.sov-file-content-preview {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--docs-border-strong);
}
.sov-file-content-title { margin-bottom: 8px; }
.sov-file-content-item {
  padding: 10px 0;
  border-top: 1px solid var(--docs-border-soft);
}
.sov-file-content-item:first-of-type { border-top: 0; }
.sov-file-content-head { gap: 8px; }
.sov-file-content-heading {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sov-file-content-text {
  margin-top: 4px;
  line-height: 1.5;
  text-wrap: pretty;
}
.sov-pdf-contour {
  margin-top: 14px;
  padding: 13px;
  border: 1px solid color-mix(in srgb, var(--accent) 38%, var(--docs-border-strong));
  border-radius: 13px;
  background: color-mix(in srgb, var(--accent) 4%, var(--bg-panel));
}
.sov-pdf-contour-head { gap: 9px; }
.sov-pdf-contour-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  border-radius: 10px;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 13%, var(--bg-panel));
}
.sov-pdf-contour-loading { gap: 7px; margin-top: 12px; }
.sov-pdf-contour-metrics { gap: 6px; margin-top: 11px; flex-wrap: wrap; }
.sov-pdf-contour-warning { margin-top: 7px; }
.sov-pdf-contour-selected {
  margin-top: 12px;
  padding: 11px;
  border: 1px solid var(--docs-border-strong);
  border-radius: 11px;
  background: var(--bg-panel);
}
.sov-pdf-contour-selected-head { gap: 6px; flex-wrap: wrap; }
.sov-pdf-contour-selected-meta { margin-top: 6px; line-height: 1.45; }
.sov-pdf-contour-preview {
  width: 100%;
  max-height: 620px;
  margin-top: 10px;
  border: 1px solid var(--docs-border-strong);
  border-radius: 8px;
  overflow: hidden;
  object-fit: contain;
  background: #fff;
}
.sov-pdf-contour-preview-placeholder {
  display: grid;
  place-items: center;
  min-height: 180px;
  margin-top: 10px;
  border: 1px dashed var(--docs-border-strong);
  border-radius: 8px;
}
.sov-pdf-contour-fragments { margin-top: 9px; }
.sov-pdf-contour-fragment-text {
  margin: 2px 0 8px;
  padding-bottom: 7px;
  border-bottom: 1px solid var(--docs-border-soft);
  line-height: 1.45;
}
.sov-pdf-page-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(92px, 1fr));
  gap: 7px;
  margin-top: 10px;
}
.sov-pdf-page-card {
  min-width: 0;
  padding: 9px;
  color: var(--text);
  text-align: left;
  border: 1px solid var(--docs-border-strong);
  border-radius: 9px;
  background: var(--bg-panel);
  cursor: pointer;
  transition: border-color 120ms ease, background-color 120ms ease, transform 120ms ease;
}
.sov-pdf-page-card:hover {
  border-color: color-mix(in srgb, var(--accent) 60%, var(--docs-border-strong));
  transform: translateY(-1px);
}
.sov-pdf-page-card--selected {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, var(--bg-panel));
}
.sov-pdf-page-card-head { justify-content: space-between; gap: 5px; }
.sov-pdf-page-card-head > .q-icon { font-size: 16px; color: var(--warn); }
.sov-pdf-page-card-type {
  margin-top: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sov-project-map {
  position: relative;
  margin-top: 12px;
  padding: 16px;
  overflow: hidden;
  border: 1px solid var(--docs-border-strong);
  border-radius: 16px;
  background:
    radial-gradient(circle at 50% 0%, color-mix(in srgb, var(--accent) 13%, transparent), transparent 42%),
    var(--bg-panel);
  box-shadow: 0 0 0 1px rgba(138,162,184,.1), 0 12px 30px rgba(3,10,18,.06);
  flex: 0 0 auto;
}
.sov-docs-view-panel > * { flex-shrink: 0; }
.sov-project-map-heading { gap: 9px; }
.sov-project-map-heading-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--accent) 14%, var(--bg-panel));
  color: var(--accent);
}
.sov-project-map-root {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  width: fit-content;
  min-width: 250px;
  margin: 18px auto 28px;
  padding: 11px 14px;
  border: 1px solid color-mix(in srgb, var(--accent) 62%, var(--docs-border-strong));
  border-radius: 13px;
  background: color-mix(in srgb, var(--accent) 10%, var(--bg-panel));
  box-shadow: 0 8px 20px color-mix(in srgb, var(--accent) 11%, transparent);
}
.sov-project-map-root > .q-icon { color: var(--accent); font-size: 23px; }
.sov-project-map-root::after {
  content: "";
  position: absolute;
  left: 50%;
  top: 100%;
  width: 1px;
  height: 29px;
  background: var(--docs-border-strong);
}
.sov-project-map-branches {
  position: relative;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.sov-project-map-branches::before {
  content: "";
  position: absolute;
  left: 16.66%;
  right: 16.66%;
  top: -14px;
  height: 1px;
  background: var(--docs-border-strong);
}
.sov-project-map-branch {
  position: relative;
  min-width: 0;
  padding: 11px;
  border: 1px solid var(--docs-border-soft);
  border-radius: 13px;
  background: color-mix(in srgb, var(--bg-panel) 94%, var(--bg));
}
.sov-project-map-branch::before {
  content: "";
  position: absolute;
  left: 50%;
  bottom: 100%;
  width: 1px;
  height: 14px;
  background: var(--docs-border-strong);
}
.sov-project-map-branch-title {
  gap: 6px;
  margin-bottom: 8px;
  color: var(--docs-muted-strong);
  text-transform: uppercase;
  letter-spacing: .06em;
}
.sov-project-map-branch-title .q-icon { color: var(--accent); font-size: 17px; }
.sov-project-map-node {
  min-height: 40px;
  margin-top: 6px;
  justify-content: flex-start;
  border: 1px solid var(--docs-border-soft);
  border-radius: 9px;
  background: var(--bg-panel);
  color: var(--text);
  font-weight: 750;
  transition-property: background-color, border-color, scale;
  transition-duration: 140ms;
}
.sov-project-map-node:hover {
  border-color: color-mix(in srgb, var(--accent) 60%, var(--docs-border-strong));
  background: color-mix(in srgb, var(--accent) 8%, var(--bg-panel));
}
.sov-project-map-node:active { scale: .96; }
.sov-project-map-stat {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  align-items: center;
  gap: 7px;
  min-height: 40px;
  margin-top: 6px;
  padding: 7px 9px;
  border: 1px solid var(--docs-border-soft);
  border-radius: 9px;
  background: var(--bg-panel);
}
.sov-project-map-stat > .q-icon { color: var(--accent); font-size: 18px; }
.sov-project-map-stat-value { color: var(--accent); font-variant-numeric: tabular-nums; }
.sov-project-map-empty { padding: 10px 4px; text-wrap: pretty; }
@media (max-width: 1080px) {
  .sov-project-map-branches { grid-template-columns: 1fr; }
  .sov-project-map-branches::before,
  .sov-project-map-branch::before,
  .sov-project-map-root::after { display: none; }
  .sov-project-map-root { margin-bottom: 12px; }
}
.sov-composition-open-file {
  min-height: 40px;
  margin-top: 12px;
  border-radius: 9px;
  background: var(--accent) !important;
  color: var(--btn-fg, #fff) !important;
}
.sov-dataset-brief-fixed {
  margin-top: 10px;
  background: var(--bg-panel);
}
.sov-dataset-brief-fixed .sov-index-brief-text {
  white-space: pre-line;
  line-height: 1.55;
  text-wrap: pretty;
}
.sov-index-brief-kicker {
  gap: 6px;
  margin-bottom: 7px;
  letter-spacing: .045em;
  text-transform: uppercase;
  color: var(--docs-muted-strong) !important;
}
.sov-index-brief-kicker .q-icon { font-size: 16px; color: var(--accent); }
.sov-index-brief-title {
  margin-bottom: 6px;
  letter-spacing: -.015em;
  text-wrap: balance;
}
.sov-index-brief-text {
  line-height: 1.55;
  color: var(--text) !important;
  font-weight: 600 !important;
  text-wrap: pretty;
  white-space: pre-wrap;
}
.sov-index-brief-meta {
  margin: 5px 0 8px 38px;
  color: var(--docs-muted-strong) !important;
  font-weight: 600 !important;
  font-variant-numeric: tabular-nums;
}
.sov-index-brief-empty-text {
  color: var(--docs-muted-strong) !important;
  font-weight: 600 !important;
  line-height: 1.5;
  text-wrap: pretty;
}
.sov-composition-file-index-source {
  color: var(--docs-muted-strong) !important;
  font-weight: 650 !important;
  font-variant-numeric: tabular-nums;
}
.sov-composition-open-file { min-height: 40px !important; width: fit-content; color: #fff !important; }
.sov-composition-folder-context {
  gap: 8px;
  margin-top: 2px;
  padding: 8px 4px 0;
}
.sov-composition-folder-description {
  padding: 0 4px 4px 44px;
  color: var(--docs-muted-strong) !important;
  font-weight: 600 !important;
}
.sov-docs-coverage { margin-top: 12px; padding: 12px 14px; }
.sov-docs-coverage-head { gap: 8px; flex-wrap: wrap; }
.sov-list-root-card,
.sov-list-discipline-card,
.sov-list-file-card {
  border-radius: 12px !important;
  transition-property: scale, box-shadow, background-color;
  transition-duration: 150ms;
}
.sov-list-file-card:hover {
  background: color-mix(in srgb, var(--bg-panel) 86%, var(--accent) 14%) !important;
  box-shadow: 0 0 0 1px rgba(52,211,153,.28), 0 10px 24px rgba(3,10,18,.06);
}
.sov-docs-shell button:active:not(:disabled),
.sov-dataset-card:active,
.sov-document-card:active,
.sov-list-file-card:active { scale: .96; }
.sov-docs-shell button { min-height: 40px; }
.sov-document-reader-summary {
  margin-top: 14px;
  padding: 14px;
  border-radius: 16px;
  background: color-mix(in srgb, var(--bg-panel) 92%, var(--accent) 8%);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--border) 74%, transparent),
              0 12px 30px rgba(3, 10, 18, .07);
}
.sov-document-reader-file,
.sov-document-reader-fragment-head { gap: 10px; flex-wrap: wrap; }
.sov-document-reader-icon {
  display: grid;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  place-items: center;
  border-radius: 10px;
  background: color-mix(in srgb, var(--accent) 15%, transparent);
  color: var(--accent);
}
.sov-document-reader-heading,
.sov-document-reader-section-title { text-wrap: balance; }
.sov-document-reader-note,
.sov-document-reader-fragment-text { text-wrap: pretty; }
.sov-document-reader-note { font-variant-numeric: tabular-nums; }
.sov-document-reader-original {
  min-height: 40px !important;
  color: var(--btn-fg, #fff) !important;
  background: var(--accent) !important;
  transition-property: transform, box-shadow, background-color;
  transition-duration: 150ms;
}
.sov-document-reader-original:active { transform: scale(.96); }
.sov-document-reader-section-title { margin-top: 18px; }
.sov-document-reader-fragment {
  margin-top: 9px;
  padding: 13px 14px;
  border-radius: 14px;
  background: var(--bg-panel);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--border) 78%, transparent),
              0 7px 20px rgba(3, 10, 18, .045);
}
.sov-document-reader-fragment-title { min-width: 180px; flex: 1; }
.sov-document-reader-source {
  max-width: 38%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sov-document-reader-fragment-text {
  margin-top: 8px;
  white-space: pre-wrap;
  line-height: 1.55;
}
.sov-document-reader-result-open { min-width: 40px; min-height: 40px !important; }
.sov-document-reader-empty,
.sov-document-reader-loading {
  display: flex;
  min-height: 150px;
  margin-top: 14px;
  padding: 22px;
  gap: 8px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  border-radius: 16px;
  background: color-mix(in srgb, var(--bg-panel) 92%, transparent);
  color: var(--dim);
  text-align: center;
}
.sov-document-reader-loading { min-height: 80px; flex-direction: row; }
.sov-studio-volume-select { min-height: 40px !important; }
.sov-mail-settings-page { padding: 22px; overflow: auto; }
.sov-mail-settings-head { gap: 12px; flex-wrap: wrap; }
.sov-mail-settings-title,
.sov-mail-settings-card-title {
  font-weight: 850;
  text-wrap: balance;
}
.sov-mail-settings-title { font-size: 1.08rem; }
.sov-mail-settings-subtitle,
.sov-mail-settings-note {
  color: var(--dim);
  line-height: 1.5;
  text-wrap: pretty;
}
.sov-mail-settings-subtitle { font-size: .76rem; }
.sov-mail-collector-card,
.sov-mail-account-card {
  display: flex;
  width: 100%;
  margin-top: 14px;
  padding: 15px 16px;
  gap: 12px;
  align-items: center;
  border-radius: 16px;
  background: var(--bg-panel);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--border) 76%, transparent),
              0 10px 26px rgba(3, 10, 18, .055);
}
.sov-mail-account-card { display: block; }
.sov-mail-settings-dataset {
  margin-top: 8px;
  font-size: .76rem;
  font-variant-numeric: tabular-nums;
}
.sov-mail-settings-loading,
.sov-mail-settings-empty { margin-top: 20px; color: var(--dim); }
.sov-mail-settings-dialog { width: min(520px, calc(100vw - 32px)); }
.sov-mail-settings-dialog-title { font-size: 1rem; font-weight: 850; text-wrap: balance; }

@media (max-width: 1180px) {
  .sov-docs-datasets-panel { width: 230px; min-width: 220px; }
  .sov-docs-files-panel { width: 350px; min-width: 320px; }
  .sov-docs-view-tab { padding-inline: 9px !important; }
}

@media (max-width: 1400px) {
  .sov-docs-view-head { flex-wrap: wrap; }
  .sov-docs-view-tabs { order: 3; width: 100%; }
  .sov-docs-view-tab { flex: 1; }
  .sov-composition-browser { grid-template-columns: 1fr; }
  .sov-composition-inspector { position: static; max-height: none; }
  .sov-composition-filters { grid-template-columns: repeat(2, minmax(180px, 1fr)); }
}

@media (max-width: 760px) {
  .sov-chat-topbar {
    align-items: flex-start;
    gap: 8px;
    flex-wrap: wrap;
  }
  .sov-scope-btn { max-width: 180px; }
  .sov-chat-thread { padding-inline: 12px !important; }
  .sov-composer {
    width: calc(100% - 20px);
    margin: 0 10px 10px;
  }
  .sov-mode-picker { gap: 4px; }
  .sov-mode-btn { padding-inline: 9px !important; }
  .sov-composer-footer { min-height: 40px; }
  .sov-mode-guide-copy { min-width: 100%; }
  .sov-mode-example { width: auto; justify-content: flex-start; }
  .sov-docs-topbar { align-items: stretch; flex-wrap: wrap; }
  .sov-docs-heading { width: 100%; }
  .sov-docs-search { width: calc(100% - 92px); margin-left: 0; }
  .sov-docs-workspace { flex-wrap: wrap !important; overflow: auto; }
  .sov-docs-datasets-panel,
  .sov-docs-files-panel,
  .sov-docs-view-panel {
    width: 100%;
    min-width: 0;
    height: auto !important;
  }
  .sov-docs-datasets-panel,
  .sov-docs-files-panel { max-height: 340px; }
  .sov-docs-view-panel { min-height: 620px; overflow: visible; }
  .sov-docs-view-head { flex-wrap: wrap; top: 0; }
  .sov-docs-view-tabs { order: 3; width: 100%; }
  .sov-docs-view-tab { flex: 1; }
}
.sov-smeta-live-table {
  max-height: 260px;
  overflow: auto;
  margin-top: 10px;
  padding: 8px 10px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--bg) 86%, var(--accent) 14%);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--border) 78%, transparent),
              0 5px 16px rgba(15, 23, 42, .06);
}
.sov-smeta-live-table table { width: 100%; margin: 0; font-size: .72rem; }
.sov-smeta-live-table th,
.sov-smeta-live-table td { padding: 5px 7px; vertical-align: top; }
.sov-smeta-live-table th:first-child,
.sov-smeta-live-table td:first-child,
.sov-smeta-live-table th:nth-child(3),
.sov-smeta-live-table td:nth-child(3) { font-variant-numeric: tabular-nums; white-space: nowrap; }
</style>
"""
