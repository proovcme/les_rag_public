"""
В.О.Л.К. v2.2 — Валидатор Ограничений Лиц и Ключей
=====================================================
Auth middleware + login page для С.О.В.У.Ш.К.А. NiceGUI.

Архитектура:
  /login         — страница входа (публичная)
  /              — основное приложение (требует cookie les_key)
  middleware     — перехватывает все запросы, проверяет cookie

Роли:
  admin  — все вкладки + В.О.Л.К. управление ключами
  user   — только AI ЧАТ

Использование в sovushka_ng.py:
  from sovushka.auth import setup_auth, get_session_role
  setup_auth(app, PROXY_URL)
"""

import asyncio
import logging
from typing import Optional

import httpx
from fastapi import Request
from fastapi.responses import RedirectResponse
from nicegui import app, ui

logger = logging.getLogger(__name__)

# ── Константы ────────────────────────────────────────────────────────────────

COOKIE_NAME    = "les_key"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30   # 30 дней
PUBLIC_PATHS   = {"/login", "/favicon.ico", "/_nicegui"}

# ── Внутренний кеш сессий (key → role) ──────────────────────────────────────
# Чтобы не дёргать /api/auth/verify при каждом запросе
_session_cache: dict[str, dict] = {}   # key → {"role": str, "holder": str}


# ── Основные функции ─────────────────────────────────────────────────────────

async def verify_key(key: str, proxy_url: str) -> Optional[dict]:
    """Проверяет ключ через proxy /api/auth/verify. Кешируем в памяти."""
    if key in _session_cache:
        return _session_cache[key]
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post(
                f"{proxy_url}/api/auth/verify",
                json={"key": key}
            )
            if r.status_code == 200:
                data = r.json()
                _session_cache[key] = data
                return data
    except Exception as e:
        logger.warning(f"[В.О.Л.К.] verify error: {e}")
    return None


def invalidate_cache(key: str):
    """Сбрасываем кеш при logout или деактивации ключа."""
    _session_cache.pop(key, None)


def get_key_from_request(request: Request) -> Optional[str]:
    """Читает les_key из cookies."""
    return request.cookies.get(COOKIE_NAME)


async def get_session(request: Request, proxy_url: str) -> Optional[dict]:
    """Возвращает {role, holder} или None."""
    key = get_key_from_request(request)
    if not key:
        return None
    return await verify_key(key, proxy_url)


# ── Middleware ───────────────────────────────────────────────────────────────

def setup_auth(nicegui_app, proxy_url: str):
    """
    Регистрирует middleware на FastAPI под NiceGUI.
    Вызывать один раз перед ui.run().

    Пример:
        from sovushka.auth import setup_auth
        setup_auth(app, PROXY_URL)
    """
    from starlette.middleware.base import BaseHTTPMiddleware

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path

            # Пропускаем публичные пути и статику NiceGUI
            if any(path.startswith(p) for p in PUBLIC_PATHS):
                return await call_next(request)

            # Проверяем cookie
            key = get_key_from_request(request)
            if key:
                session = await verify_key(key, proxy_url)
                if session:
                    return await call_next(request)

            # Не авторизован — редирект на /login
            # Для API-запросов возвращаем 401
            if path.startswith("/api/"):
                from starlette.responses import JSONResponse
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)

            return RedirectResponse(url="/login")

    nicegui_app.middleware("http")(AuthMiddleware)
    logger.info("[В.О.Л.К.] Auth middleware зарегистрирован")


# ── Login page ───────────────────────────────────────────────────────────────

LOGIN_CSS = """
<style>
.volk-overlay {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg, #08090b);
  font-family: 'Courier New', monospace;
}
.volk-card {
  background: var(--bg-panel, #12151a);
  border: 1px solid var(--border, #2d3748);
  border-radius: 12px;
  padding: 40px 48px;
  width: 380px;
}
.volk-logo {
  font-size: 1.4rem;
  font-weight: 900;
  color: var(--accent, #3b82f6);
  letter-spacing: 1px;
  margin-bottom: 4px;
}
.volk-sub {
  font-size: .65rem;
  color: var(--dim, #94a3b8);
  margin-bottom: 28px;
  letter-spacing: .3px;
}
.volk-label {
  font-size: .65rem;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--dim, #94a3b8);
  letter-spacing: .4px;
  margin-bottom: 6px;
}
.volk-input {
  width: 100%;
  background: var(--bg, #08090b);
  border: 1px solid var(--border, #2d3748);
  color: #fff;
  font-family: 'Courier New', monospace;
  font-size: .9rem;
  border-radius: 6px;
  padding: 11px 14px;
  box-sizing: border-box;
  outline: none;
  margin-bottom: 16px;
  transition: border-color .2s;
}
.volk-input:focus { border-color: var(--accent, #3b82f6); }
.volk-btn {
  width: 100%;
  background: rgba(59,130,246,.15);
  border: 1px solid var(--accent, #3b82f6);
  color: var(--accent, #3b82f6);
  font-family: 'Courier New', monospace;
  font-weight: 900;
  font-size: .8rem;
  letter-spacing: .5px;
  border-radius: 6px;
  padding: 11px;
  cursor: pointer;
  transition: background .2s;
}
.volk-btn:hover { background: rgba(59,130,246,.28); }
.volk-btn:disabled { opacity: .5; cursor: not-allowed; }
.volk-err {
  color: var(--err, #ef4444);
  font-size: .7rem;
  margin-top: 10px;
  min-height: 18px;
  text-align: center;
}
.volk-footer {
  font-size: .58rem;
  color: var(--border, #2d3748);
  text-align: center;
  margin-top: 24px;
  letter-spacing: .3px;
}
</style>
"""


def register_login_page(proxy_url: str, cookie_name: str = COOKIE_NAME,
                        cookie_max_age: int = COOKIE_MAX_AGE):
    """
    Регистрирует страницу /login.
    Вызывать до ui.run().
    """
    @ui.page("/login")
    async def login_page(request: Request):
        # Уже авторизован — сразу на главную
        key = get_key_from_request(request)
        if key and await verify_key(key, proxy_url):
            ui.navigate.to("/")
            return

        ui.add_head_html(LOGIN_CSS)
        ui.query("body").style("background:#08090b;margin:0;")

        ui.html(f"""
<div class="volk-overlay">
  <div class="volk-card">
    <div class="volk-logo">[O_O] С.О.В.У.Ш.К.А.</div>
    <div class="volk-sub">Л.Е.С. // Система анализа нормативной документации</div>

    <div class="volk-label">Ключ доступа</div>
    <input
      class="volk-input"
      id="volk-key"
      type="password"
      placeholder="les_xxxxxxxxxxxxxxxx"
      autocomplete="current-password"
      onkeydown="if(event.key==='Enter') volkLogin()"
    >
    <button class="volk-btn" id="volk-btn" onclick="volkLogin()">
      ▶ ВОЙТИ В СИСТЕМУ
    </button>
    <div class="volk-err" id="volk-err"></div>
    <div class="volk-footer">В.О.Л.К. v2.2 · les.ovc.me</div>
  </div>
</div>

<script>
async function volkLogin() {{
  const key  = document.getElementById('volk-key').value.trim();
  const err  = document.getElementById('volk-err');
  const btn  = document.getElementById('volk-btn');
  if (!key) {{ err.textContent = 'Введите ключ доступа'; return; }}

  btn.disabled = true;
  btn.textContent = '...';
  err.textContent = '';

  try {{
    const r = await fetch('{proxy_url}/api/auth/verify', {{
      method:  'POST',
      headers: {{'Content-Type': 'application/json'}},
      body:    JSON.stringify({{key}})
    }});
    if (r.ok) {{
      document.cookie = '{cookie_name}=' + encodeURIComponent(key)
        + '; path=/; max-age={cookie_max_age}; SameSite=Lax';
      window.location.href = '/';
    }} else {{
      const d = await r.json().catch(() => {{}});
      err.textContent = d.detail || 'Неверный ключ или ключ отключён';
      btn.disabled = false;
      btn.textContent = '▶ ВОЙТИ В СИСТЕМУ';
      document.getElementById('volk-key').focus();
    }}
  }} catch(e) {{
    err.textContent = 'Ошибка соединения с сервером';
    btn.disabled = false;
    btn.textContent = '▶ ВОЙТИ В СИСТЕМУ';
  }}
}}
document.getElementById('volk-key').focus();
</script>
""", sanitize=False)
