"""
С.О.В.У.Ш.К.А. v5.0 — Страница /login (В.О.Л.К. auth)

Использует только NiceGUI-компоненты + ui.add_body_html() для JS.
НЕ использует ui.html() со <script> — это вызывает ValueError в NiceGUI 3.6.1.
"""
from __future__ import annotations

import json
import httpx
from fastapi import Request
from nicegui import app, ui
from starlette.responses import RedirectResponse

from backend.auth import login, is_authenticated, get_role, get_holder, logout
from sovushka.trust import trusted_role_for_request

# ── Цитаты В.О.Л.К. ──────────────────────────────────────────────────────────

_QUOTES = [
    "Один волк в системе сильнее стаи снаружи.",
    "Стая держится на доверии. Ключ — это доверие.",
    "Волк не лает попусту. Доступ — или нет.",
    "Чужих здесь не бывает. Только те, кто знает.",
    "В лесу свои правила. Входи или уходи.",
    "Я помню всех, кто входил. И всех, кто пытался.",
    "Зубы не нужны, если знаешь пароль.",
]

# ── CSS страницы /login ───────────────────────────────────────────────────────

_LOGIN_CSS = """
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #08090b !important; }
.volk-wrap {
  min-height: 100vh;
  background: #08090b;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'Courier New', Courier, monospace;
  padding: 2rem 1rem;
}
.volk-card {
  background: #0d1117;
  border: 1px solid #1e2d3d;
  border-radius: 12px;
  padding: 40px 48px 36px;
  width: 420px;
  position: relative;
}
.volk-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, #0d1117, #3b82f6, #0d1117);
}
.volk-logo-main {
  font-size: 2rem;
  font-weight: 900;
  color: #3b82f6;
  letter-spacing: 6px;
  text-align: center;
  display: block;
  margin-bottom: 6px;
}
.volk-logo-full {
  font-size: .58rem;
  color: #2d4a6e;
  letter-spacing: .3px;
  text-align: center;
  display: block;
  margin-bottom: 3px;
}
.volk-logo-sub {
  font-size: .55rem;
  color: #1a2e42;
  letter-spacing: .4px;
  text-transform: uppercase;
  text-align: center;
  display: block;
  margin-bottom: 24px;
}
.volk-divider {
  border: none;
  border-top: 1px solid #1a2535;
  margin: 0 0 20px;
}
.volk-quote {
  font-size: .68rem;
  color: #1e3a5f;
  text-align: center;
  font-style: italic;
  margin-bottom: 28px;
  min-height: 20px;
  line-height: 1.5;
  transition: color .5s, opacity .5s;
  opacity: 0;
}
.volk-quote.show { color: #4b7baa; opacity: 1; }
.volk-label {
  font-size: .58rem;
  font-weight: 700;
  text-transform: uppercase;
  color: #2d3f52;
  letter-spacing: .5px;
  margin-bottom: 6px;
}
.volk-input {
  width: 100%;
  background: #08090b;
  border: 1px solid #1e2d3d;
  color: #94a3b8;
  font-family: 'Courier New', monospace;
  font-size: .82rem;
  border-radius: 6px;
  padding: 10px 13px;
  outline: none;
  margin-bottom: 12px;
  transition: border-color .2s, color .2s;
}
.volk-input:focus { border-color: #3b82f6; color: #e2e8f0; }
.volk-btn {
  width: 100%;
  background: rgba(59,130,246,.08);
  border: 1px solid #1e3a5f;
  color: #3b82f6;
  font-family: 'Courier New', monospace;
  font-weight: 900;
  font-size: .72rem;
  letter-spacing: 1.5px;
  border-radius: 6px;
  padding: 10px;
  cursor: pointer;
  transition: background .2s, border-color .2s;
}
.volk-btn:hover { background: rgba(59,130,246,.2); border-color: #3b82f6; }
.volk-btn:disabled { opacity: .5; cursor: not-allowed; }
.volk-err {
  color: #ef4444;
  font-size: .62rem;
  margin-top: 9px;
  min-height: 15px;
  text-align: center;
}
.volk-foot {
  font-size: .52rem;
  color: #141d2b;
  text-align: center;
  margin-top: 22px;
  letter-spacing: .3px;
}
/* Скрываем стандартный nicegui контейнер на странице логина */
.nicegui-content { padding: 0 !important; background: transparent !important; }
</style>
"""

# ── Страница /login ───────────────────────────────────────────────────────────

def register_login_page():
    """Регистрирует /login страницу через @ui.page. Вызвать до ui.run()."""

    @ui.page("/login")
    async def login_page(request: Request):
        trusted_role = trusted_role_for_request(request)
        
        if is_authenticated() or trusted_role:
            role = trusted_role or get_role()
            return RedirectResponse("/les" if role == "admin" else "/")

        ui.add_head_html(_LOGIN_CSS)
        ui.query("body").style("background:#08090b;margin:0;")

        quotes_json = json.dumps(_QUOTES, ensure_ascii=False)
        ui.add_body_html(f"""
<div class="volk-wrap">
  <div class="volk-card">
    <span class="volk-logo-main">В.О.Л.К.</span>
    <span class="volk-logo-full">Внутренний Охранный Локальный Контур</span>
    <span class="volk-logo-sub">Л.Е.С. &middot; Система контроля доступа</span>
    <hr class="volk-divider">
    <div class="volk-quote" id="volk-q"></div>
    <div class="volk-label">Ключ доступа</div>
    <input class="volk-input" id="volk-key" type="password"
           placeholder="les_xxxxxxxxxxxxxxxx"
           onkeydown="if(event.key==='Enter')volkLogin()">
    <button class="volk-btn" id="volk-btn" onclick="volkLogin()">&#9654;&nbsp;&nbsp;ВОЙТИ В СИСТЕМУ</button>
    <div class="volk-err" id="volk-err"></div>
    <div class="volk-foot">localhost &middot; Л.Е.С. &middot; доступ только по ключу</div>
  </div>
</div>
<script>
(function(){{
  var qs = {quotes_json};
  var qi = Math.floor(Math.random() * qs.length);
  var qEl = document.getElementById('volk-q');
  function showQ() {{
    if(!qEl) return;
    qEl.classList.remove('show');
    setTimeout(function() {{
      qEl.textContent = '\u00ab' + qs[qi] + '\u00bb';
      qEl.classList.add('show');
      qi = (qi + 1) % qs.length;
    }}, 400);
  }}
  showQ();
  setInterval(showQ, 4500);
  setTimeout(function(){{ document.getElementById('volk-key').focus(); }}, 150);
}})();

function volkFingerprint() {{
  var c = [];
  c.push(navigator.userAgent || '');
  c.push((navigator.languages || [navigator.language || '']).join(','));
  c.push(screen.width + 'x' + screen.height + 'x' + (screen.colorDepth || 24));
  c.push(navigator.hardwareConcurrency || 0);
  c.push(Intl.DateTimeFormat().resolvedOptions().timeZone || '');
  c.push(navigator.platform || '');
  try {{
    var cv = document.createElement('canvas');
    var cx = cv.getContext('2d');
    cx.textBaseline = 'top';
    cx.font = '14px monospace';
    cx.fillStyle = '#3b82f6';
    cx.fillRect(0, 0, 80, 20);
    cx.fillStyle = '#ffffff';
    cx.fillText('Л.Е.С. 🔑', 2, 4);
    c.push(cv.toDataURL().slice(-64));
  }} catch(e) {{}}
  var s = c.join('|'), h = 5381;
  for (var i = 0; i < s.length; i++) {{ h = ((h << 5) + h) ^ s.charCodeAt(i); h = h >>> 0; }}
  return 'fp_' + h.toString(16).padStart(8, '0');
}}

function volkLogin() {{
  var key = document.getElementById('volk-key').value.trim();
  var err = document.getElementById('volk-err');
  var btn = document.getElementById('volk-btn');
  if (!key) {{ err.textContent = 'Введите ключ доступа'; return; }}
  btn.disabled = true; btn.textContent = '...'; err.textContent = '';
  window.__volkKey = key;
  window.__volkFp  = volkFingerprint();
  document.getElementById('_volk_trigger').click();
}}
</script>
""")

        # Скрытая кнопка-мост JS → Python
        async def _handle_login():
            key_val = await ui.run_javascript("return window.__volkKey || '';")
            fp_val  = await ui.run_javascript("return window.__volkFp  || '';")
            if not key_val:
                return
            result = await login(key_val, fingerprint=fp_val)
            if result["ok"]:
                ui.navigate.to("/les" if get_role() == "admin" else "/")
            else:
                msg = result.get("detail", "Неверный ключ или ключ отключён")
                await ui.run_javascript(
                    f"document.getElementById('volk-err').textContent={msg!r};"
                    "var b=document.getElementById('volk-btn');"
                    "b.disabled=false;b.textContent='\\u25BA\\u00A0\\u00A0ВОЙТИ В СИСТЕМУ';"
                    "document.getElementById('volk-key').focus();"
                    "window.__volkKey='';window.__volkFp='';"
                )

        ui.button("", on_click=_handle_login).props('id="_volk_trigger"').style("visibility:hidden;position:absolute;")


# ── Хелпер для main_page ─────────────────────────────────────────────────────

def get_auth():
    """Возвращает (is_auth, role, holder) для текущей NiceGUI-сессии."""
    return is_authenticated(), get_role(), get_holder()
