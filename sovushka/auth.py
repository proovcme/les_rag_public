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

from backend.auth import login, is_authenticated, get_role, get_holder, logout

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
        forwarded = request.headers.get("x-forwarded-for")
        real_ip = request.headers.get("x-real-ip")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        elif real_ip:
            client_ip = real_ip.strip()
        else:
            client_ip = request.client.host if request and request.client else "127.0.0.1"
            
        is_local = any(client_ip.startswith(p) for p in ("127.", "10.", "192.168.", "172.", "::1"))
        
        if is_authenticated() or is_local:
            ui.navigate.to("/")
            return

        # CSS — без скриптов, только стили
        ui.add_head_html(_LOGIN_CSS)
        ui.query("body").style("background:#08090b;margin:0;")

        with ui.element('div').classes('volk-wrap'):
            with ui.element('div').classes('volk-card'):
                ui.label('В.О.Л.К.').classes('volk-logo-main')
                ui.element('span').classes('volk-logo-full').set_text('Внутренний Охранный Локальный Контур')
                ui.element('span').classes('volk-logo-sub').set_text('Л.Е.С. · Система контроля доступа')
                ui.element('hr').classes('volk-divider')
                
                quote_div = ui.element('div').classes('volk-quote show').props('id="volk-q"')
                
                ui.element('div').classes('volk-label').set_text('Ключ доступа')
                
                key_input = ui.element('input').classes('volk-input').props(
                    'type="password" placeholder="les_xxxxxxxxxxxxxxxx" id="volk-key-native"'
                )
                
                err_label = ui.element('div').classes('volk-err').props('id="volk-err-native"')
                
                async def do_login(e=None):
                    key_val = await ui.run_javascript("document.getElementById('volk-key-native').value.trim()")
                    if not key_val:
                        err_label.set_text('Введите ключ доступа')
                        return
                    
                    err_label.set_text('')
                    submit_btn.props('disabled')
                    submit_btn.set_text('...')
                    
                    success = await login(key_val)
                    
                    if success:
                        ui.navigate.to("/")
                    else:
                        submit_btn.props(remove='disabled')
                        submit_btn.set_text('▶  ВОЙТИ В СИСТЕМУ')
                        err_label.set_text('Неверный ключ или ключ отключён')
                        await ui.run_javascript("document.getElementById('volk-key-native').focus()")

                key_input.on('keydown.enter', do_login)
                
                submit_btn = ui.element('button').classes('volk-btn').set_text('▶  ВОЙТИ В СИСТЕМУ')
                submit_btn.on('click', do_login)
                
                ui.element('div').classes('volk-foot').set_text('les.ovc.me · Л.Е.С. · доступ только по ключу')

        # JS-скрипт цитат
        quotes_json = json.dumps(_QUOTES, ensure_ascii=False)
        ui.add_body_html(f"""
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
  
  setTimeout(() => document.getElementById('volk-key-native').focus(), 100);
}})();
</script>
""")


# ── Хелпер для main_page ─────────────────────────────────────────────────────

def get_auth():
    """Возвращает (is_auth, role, holder) для текущей NiceGUI-сессии."""
    return is_authenticated(), get_role(), get_holder()
