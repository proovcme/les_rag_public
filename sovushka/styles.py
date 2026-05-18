"""
С.О.В.У.Ш.К.А. v5.0 — CSS стили
"""

CUSTOM_CSS = """
<style>
:root {
  --bg:       #08090b;
  --bg-panel: #12151a;
  --bg-mod:   #1a1e25;
  --text:     #ffffff;
  --dim:      #94a3b8;
  --border:   #2d3748;
  --accent:   #3b82f6;
  --ok:       #10b981;
  --pauk:     #8b5cf6;
  --warn:     #f59e0b;
  --err:      #ef4444;
  --font:     'Courier New', Courier, monospace;
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
.chat-msg-user { align-self:flex-end; background:var(--border); color:var(--text); border-right:3px solid var(--pauk); border-radius:6px; padding:10px 14px; max-width:80%; font-size:.8rem; line-height:1.5; }
.chat-msg-ai   { align-self:flex-start; background:var(--bg-panel); color:var(--text); border:1px solid var(--border); border-left:3px solid var(--accent); border-radius:6px; padding:10px 14px; max-width:85%; font-size:.8rem; line-height:1.5; }
.chat-msg-sys  { align-self:center; color:var(--dim); font-size:.7rem; border:1px solid var(--border); border-radius:4px; padding:4px 12px; }
.src-tag { font-size:.6rem; font-weight:700; padding:2px 6px; border:1px solid var(--ok); color:var(--ok); border-radius:4px; margin-right:4px; }
.src-tag-err { border-color:var(--err); color:var(--err); }
.typing::after { content:'▋'; animation:blink 1s step-end infinite; opacity:.7; margin-left:4px; }
@keyframes blink { 50%{opacity:0} }
</style>
"""
