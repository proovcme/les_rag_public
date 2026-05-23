"""
С.О.В.У.Ш.К.А. v5.0 — Модульная точка входа
"""
import asyncio
from fastapi import Request
from nicegui import app, ui
from starlette.responses import RedirectResponse

from sovushka.config import STORAGE_SECRET, UI_PORT
from sovushka.state import bg_loop
from sovushka.styles import CUSTOM_CSS, theme_vars_css
from sovushka.auth import register_login_page, get_auth
from sovushka.trust import trusted_role_for_request

from sovushka.components.header import build_header
from sovushka.components.logterm import build_log_terminal

from sovushka.pages.overview import build_overview
from sovushka.pages.samovar import build_samovar
from sovushka.pages.prorab import build_prorab
from sovushka.pages.chat import build_chat
from sovushka.pages.history import build_history
from sovushka.pages.mermaid_page import build_mermaid
from sovushka.pages.diag import build_diag
from sovushka.pages.volk import build_volk


# ── Статические файлы ──
app.add_static_files("/static", "static")

# Регистрируем /login (отдельная страница, без обвязки main_page)
register_login_page()


def _apply_theme() -> None:
    """Inject theme CSS before rendering the page body."""
    _dark = app.storage.user.get("dark_theme", True)
    ui.add_head_html(theme_vars_css(_dark))
    ui.add_head_html(CUSTOM_CSS)
    ui.query("body").style("background:var(--bg);color:var(--text);margin:0;")
    ui.query(".nicegui-content").classes("p-0 m-0 w-full").style("max-width:none;")


def _resolve_auth(request: Request):
    is_auth, role, holder = get_auth()

    trusted_role = trusted_role_for_request(request)

    if not is_auth and not trusted_role:
        return False, None, None, False

    if not is_auth and trusted_role:
        role = trusted_role
        holder = "Trusted Network"

    is_admin = (role == "admin")
    return True, role, holder, is_admin


@ui.page("/")
async def chat_page(request: Request):
    allowed, role, holder, is_admin = _resolve_auth(request)
    if not allowed:
        return RedirectResponse("/login")

    _apply_theme()

    # Public shell: only chat/history. It stays lean and avoids mounting admin pages.
    with ui.column().classes("w-full h-screen no-wrap gap-0"):
        tabs, tr = build_header(
            is_admin,
            role,
            holder,
            admin_tabs=False,
            admin_link=is_admin,
        )

        tab_chat = tr["chat"]
        tab_history = tr["history"]

        def _save_chat_tab(e):
            try:
                val = e.args if isinstance(e.args, str) else (e.args[0] if isinstance(e.args, (list, tuple)) and e.args else None)
                if val:
                    app.storage.user["last_chat_tab"] = str(val)
            except Exception:
                pass

        tabs.on("update:model-value", _save_chat_tab)

        with ui.tab_panels(tabs, value=tab_chat).classes("w-full flex-1").style(
            "background:var(--bg);overflow-y:auto;padding:0;"
        ):
            with ui.tab_panel(tab_chat):
                build_chat(is_admin, tabs, None)
            with ui.tab_panel(tab_history):
                build_history(tabs, tab_chat)

    _last_tab = app.storage.user.get("last_chat_tab", "AI ЧАТ")
    _target = {"AI ЧАТ": tab_chat, "ИСТОРИЯ": tab_history}.get(_last_tab)
    if _target and _target != tab_chat:
        tabs.set_value(_target)


@ui.page("/les")
@ui.page("/les/")
async def admin_page(request: Request):
    allowed, role, holder, is_admin = _resolve_auth(request)
    if not allowed:
        return RedirectResponse("/login")

    if not is_admin:
        return RedirectResponse("/")

    _apply_theme()

    # Layout: Header (со встроенными табами) + Content + Footer
    with ui.column().classes("w-full h-screen no-wrap gap-0"):

        # Единая полоса: лого + табы + контролы
        tabs, tr = build_header(is_admin, role, holder, include_chat=False, chat_link=True)

        tab_overview = tr.get("overview")
        tab_samovar  = tr.get("samovar")
        tab_prorab   = tr.get("prorab")
        tab_mermaid  = tr.get("mermaid")
        tab_diag     = tr.get("diag")
        tab_volk     = tr.get("volk")

        # Персистим активный таб
        def _save_tab(e):
            try:
                val = e.args if isinstance(e.args, str) else (e.args[0] if isinstance(e.args, (list, tuple)) and e.args else None)
                if val:
                    app.storage.user["last_tab"] = str(val)
            except Exception:
                pass
        tabs.on("update:model-value", _save_tab)

        # Контент
        _default_tab = tab_overview
        with ui.tab_panels(tabs, value=_default_tab).classes("w-full flex-1").style(
            "background:var(--bg);overflow-y:auto;padding:0;"
        ):
            with ui.tab_panel(tab_overview):
                build_overview(tabs, is_admin)
            with ui.tab_panel(tab_samovar):
                build_samovar()
            with ui.tab_panel(tab_prorab):
                build_prorab()
            with ui.tab_panel(tab_mermaid):
                build_mermaid()
            with ui.tab_panel(tab_diag):
                build_diag()
            with ui.tab_panel(tab_volk):
                build_volk()

        # Подвал (Лог)
        build_log_terminal()

    # Восстанавливаем последний активный таб
    _last_tab = app.storage.user.get("last_tab", "ОБЗОР")
    _tab_map = {
        "ОБЗОР":          tab_overview,
        "С.А.М.О.В.А.Р.": tab_samovar,
        "П.Р.О.Р.А.Б.":   tab_prorab,
        "ГРАФ":            tab_mermaid,
        "🔬 ДИАГН":        tab_diag,
        "В.О.Л.К.":       tab_volk,
    }
    _target = _tab_map.get(_last_tab)
    if _target and _target != _default_tab:
        tabs.set_value(_target)



if __name__ in {"__main__", "__mp_main__"}:
    # Фоновые задачи запускаем при старте UI
    app.on_startup(lambda: asyncio.create_task(bg_loop()))
    
    ui.run(
        port=UI_PORT,
        title="Л.Е.С. v5.0",
        dark=True,
        show=False,
        storage_secret=STORAGE_SECRET,
        reload=False,
        reconnect_timeout=180,  # длинные RAG-запросы не должны срывать страницу
    )
