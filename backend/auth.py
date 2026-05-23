"""
В.О.Л.К. v2.3 — Внутренний Охранный Локальный Контур
======================================================
Auth для С.О.В.У.Ш.К.А. через app.storage.user (NiceGUI-way).

Никакого middleware, никаких ручных cookies.
Требует storage_secret в ui.run().

API:
    is_authenticated() -> bool
    get_role()         -> str   # "admin" | "user"
    get_holder()       -> str   # имя владельца ключа
    login(key)         -> bool  # async
    logout()           -> None
    register_login_page()       # вызвать до ui.run()
"""

import logging
import httpx
from nicegui import app, ui

logger = logging.getLogger(__name__)

PROXY_URL = "http://localhost:8050"

# ── Состояние сессии ─────────────────────────────────────────────────────────

def is_authenticated() -> bool:
    return app.storage.user.get("authenticated", False)

def get_role() -> str:
    return app.storage.user.get("role", "user")

def get_holder() -> str:
    return app.storage.user.get("holder", "")

async def login(key: str, fingerprint: str = "") -> dict:
    """Проверяет ключ через proxy /api/auth/verify, сохраняет сессию.
    Возвращает {"ok": bool, "detail": str}."""
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post(
                f"{PROXY_URL}/api/auth/verify",
                json={"key": key.strip(), "fingerprint": fingerprint.strip()}
            )
            if r.status_code == 200:
                data = r.json()
                app.storage.user["authenticated"] = True
                app.storage.user["role"]          = data.get("role", "user")
                app.storage.user["holder"]        = data.get("holder", "")
                app.storage.user["key"]           = key.strip()
                logger.info(f"[В.О.Л.К.] Вход: {data.get('holder')} [{data.get('role')}]")
                return {"ok": True}
            else:
                detail = r.json().get("detail", "Ошибка авторизации") if r.headers.get("content-type", "").startswith("application/json") else "Ошибка авторизации"
                return {"ok": False, "detail": detail}
    except Exception as e:
        logger.warning(f"[В.О.Л.К.] Ошибка verify: {e}")
        return {"ok": False, "detail": "Ошибка соединения с сервером"}

def logout():
    app.storage.user.clear()
    logger.info("[В.О.Л.К.] Выход из системы")


# ── CSS страницы логина ───────────────────────────────────────────────────────

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
</style>
"""

_QUOTES = [
    "Один волк в системе сильнее стаи снаружи.",
    "Стая держится на доверии. Ключ — это доверие.",
    "Волк не лает попусту. Доступ — или нет.",
    "Чужих здесь не бывает. Только те, кто знает.",
    "В лесу свои правила. Входи или уходи.",
    "Я помню всех, кто входил. И всех, кто пытался.",
    "Зубы не нужны, если знаешь пароль.",
]

_LOGIN_JS = """
<script>
(function(){
  const qs=%s;
  let qi=Math.floor(Math.random()*qs.length);
  const qEl=document.getElementById('volk-q');
  function showQ(){
    qEl.classList.remove('show');
    setTimeout(()=>{
      qEl.textContent='\u00ab'+qs[qi]+'\u00bb';
      qEl.classList.add('show');
      qi=(qi+1)%%qs.length;
    },400);
  }
  showQ();
  setInterval(showQ,4500);
})();
</script>
""" % str(_QUOTES).replace("'", '"')


# ── Страница /login ───────────────────────────────────────────────────────────

def register_login_page():
    """Регистрирует /login. Вызвать до ui.run()."""

    @ui.page("/login")
    async def login_page():
        if is_authenticated():
            ui.navigate.to("/")
            return

        ui.add_head_html(_LOGIN_CSS)
        ui.query("body").style("background:#08090b;margin:0;")

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
           onkeydown="if(event.key==='Enter') volkLogin()">
    <button class="volk-btn" id="volk-btn" onclick="volkLogin()">
      &#9654;&nbsp;&nbsp;ВОЙТИ В СИСТЕМУ
    </button>
    <div class="volk-err" id="volk-err"></div>
    <div class="volk-foot">les.ovc.me &middot; Л.Е.С. &middot; доступ только по ключу</div>
  </div>
</div>
<script>
async function volkLogin() {{
  const key = document.getElementById('volk-key').value.trim();
  const err = document.getElementById('volk-err');
  const btn = document.getElementById('volk-btn');
  if (!key) {{ err.textContent = 'Введите ключ доступа'; return; }}
  btn.disabled = true;
  btn.textContent = '...';
  err.textContent = '';
  try {{
    const r = await fetch('{PROXY_URL}/api/auth/verify', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{key}})
    }});
    if (r.ok) {{
      window.location.href = '/';
    }} else {{
      const d = await r.json().catch(()=>({{}}));
      err.textContent = d.detail || 'Неверный ключ или ключ отключён';
      btn.disabled = false;
      btn.textContent = '\\u25BA\\u00A0\\u00A0ВОЙТИ В СИСТЕМУ';
      document.getElementById('volk-key').focus();
    }}
  }} catch(e) {{
    err.textContent = 'Ошибка соединения с сервером';
    btn.disabled = false;
    btn.textContent = '\\u25BA\\u00A0\\u00A0ВОЙТИ В СИСТЕМУ';
  }}
}}
document.getElementById('volk-key').focus();
</script>
""", sanitize=False)

        ui.add_body_html(_LOGIN_JS)
