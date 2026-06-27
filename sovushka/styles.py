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
    "--bg":       "#eef3f8",
    "--bg-panel": "#ffffff",
    "--bg-mod":   "#e3ebf4",
    "--text":     "#0b1220",
    "--dim":      "#2f3f53",
    "--border":   "#60758c",
    "--accent":   "#047857",
    "--ok":       "#006d3a",
    "--pauk":     "#6d28d9",
    "--warn":     "#8a4b00",
    "--err":      "#b91c1c",
    "--shell-bg": "linear-gradient(180deg, #f8fafc 0%, #e4ebf3 100%)",
    "--panel-glass": "rgba(255,255,255,.96)",
    "--panel-top": "rgba(237,244,251,.96)",
    "--scroll-bg": "linear-gradient(180deg, #f7fafc 0%, #edf3f9 100%)",
    "--composer-bg": "#ffffff",
    "--artifact-bg": "#f5f8fc",
    "--card-bg": "#ffffff",
    "--input-bg": "#ffffff",
    "--shadow-strong": "0 14px 40px rgba(15,23,42,.14), inset 0 1px 0 rgba(255,255,255,.85)",
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
.sov-chat-message-text { white-space:pre-wrap; overflow-wrap:anywhere; }
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
.chat-msg-user, .chat-msg-ai { min-width: 0; overflow-wrap: anywhere; word-break: break-word; }
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

/* Богатые формы прямо в пузыре чата: таблицы, mermaid-диаграммы, проза-сегменты. */
.sov-chat-rich { align-items: stretch; }
.sov-chat-md { white-space: normal; }
.sov-chat-md p { margin: .2rem 0; }
.sov-chat-inline-table {
  width: 100%;
  background: var(--bg-panel);
  color: var(--text);
  font-size: .76rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
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
.q-card, .q-card__section { color: var(--text) !important; }
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

/* Inline-таблица в чате: читаемее, не «терминал». */
.sov-chat-inline-table { font-family: var(--font); font-size: .74rem; }
.sov-chat-inline-table thead th {
  position: sticky; top: 0;
  background: var(--bg-mod) !important;
  font-weight: 800; letter-spacing: .02em;
}
.sov-chat-inline-table td, .sov-chat-inline-table th { font-variant-numeric: tabular-nums; }

/* v0.20 — действия ответа (Копировать), бейдж версии, меню примеров. */
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
</style>
"""
