"""
С.О.В.У.Ш.К.А. v5.0 — Модульная точка входа
"""
import asyncio
from fastapi import Request
from nicegui import app, ui

from sovushka.config import UI_PORT
from sovushka.state import bg_loop
from sovushka.styles import CUSTOM_CSS, theme_vars_css
from sovushka.auth import register_login_page, get_auth

from sovushka.components.header import build_header
from sovushka.components.logterm import build_log_terminal

from sovushka.pages.overview import build_overview
from sovushka.pages.samovar import build_samovar
from sovushka.pages.prorab import build_prorab
from sovushka.pages.chat import build_chat
from sovushka.pages.mermaid_page import build_mermaid
from sovushka.pages.diag import build_diag
from sovushka.pages.volk import build_volk


# ── Статические файлы ──
app.add_static_files("/static", "static")

# Регистрируем /login (отдельная страница, без обвязки main_page)
register_login_page()


@ui.page("/")
async def main_page(request: Request):
    is_auth, role, holder = get_auth()
    
    forwarded = request.headers.get("x-forwarded-for")
    real_ip = request.headers.get("x-real-ip")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    elif real_ip:
        client_ip = real_ip.strip()
    else:
        client_ip = request.client.host if request and request.client else "127.0.0.1"
        
    is_local = any(client_ip.startswith(p) for p in ("127.", "10.", "192.168.", "172.", "::1"))
    
    if not is_auth and not is_local:
        ui.navigate.to("/login")
        return

    if not is_auth and is_local:
        role = "admin"
        holder = "Local (Auto)"
        
    is_admin = (role == "admin")

    # Тема — инжектируем CSS-переменные СИНХРОННО в <head> до рендера.
    # Это устраняет flash: браузер получает правильные цвета сразу, без JS-таймера.
    _dark = app.storage.user.get("dark_theme", True)
    ui.add_head_html(theme_vars_css(_dark))
    ui.add_head_html(CUSTOM_CSS)
    ui.query("body").style("background:var(--bg);color:var(--text);margin:0;")
    ui.query(".nicegui-content").classes("p-0 m-0 w-full").style("max-width:none;")

    # Layout: Header + Tabs + Content + Footer
    with ui.column().classes("w-full h-screen no-wrap gap-0"):

        # Создаем табы
        with ui.tabs().classes("w-full bg-panel border-b border-border text-dim").style(
            "background:var(--bg-panel);border-bottom:1px solid var(--border);"
            "color:var(--dim);font-family:var(--font);font-size:.7rem;font-weight:700;"
            "padding:0 24px;"
        ) as tabs:
            tab_overview = ui.tab("ОБЗОР",          icon="o_dashboard") if is_admin else None
            tab_samovar  = ui.tab("С.А.М.О.В.А.Р.", icon="o_inventory_2") if is_admin else None
            tab_prorab   = ui.tab("П.Р.О.Р.А.Б.",   icon="o_monitor") if is_admin else None
            tab_chat     = ui.tab("AI ЧАТ",         icon="o_forum")
            tab_mermaid  = ui.tab("ГРАФ",           icon="o_account_tree") if is_admin else None
            tab_diag     = ui.tab("🔬 ДИАГНОСТИКА", icon="o_medical_services") if is_admin else None
            tab_volk     = ui.tab("В.О.Л.К.",       icon="o_vpn_key") if is_admin else None

        # Персистим активный таб — при любом переключении сохраняем имя
        def _save_tab(e):
            try:
                val = e.args if isinstance(e.args, str) else (e.args[0] if isinstance(e.args, (list, tuple)) and e.args else None)
                if val:
                    app.storage.user["last_tab"] = str(val)
            except Exception:
                pass

        tabs.on("update:model-value", _save_tab)

        # Шапка (после tabs, чтобы sticky работал корректно)
        build_header(tabs, role, holder, is_admin)

        # 2. Контент (Panels)
        _default_tab = tab_overview if is_admin else tab_chat
        with ui.tab_panels(tabs, value=_default_tab).classes("w-full flex-1").style(
            "background:var(--bg);overflow-y:auto;padding:0;"
        ):
            if is_admin:
                with ui.tab_panel(tab_overview):
                    build_overview(tabs, is_admin)
                with ui.tab_panel(tab_samovar):
                    build_samovar()
                with ui.tab_panel(tab_prorab):
                    build_prorab()
            with ui.tab_panel(tab_chat):
                build_chat(is_admin, tabs, tab_mermaid)
            if is_admin:
                with ui.tab_panel(tab_mermaid):
                    build_mermaid()
                with ui.tab_panel(tab_diag):
                    build_diag()
                with ui.tab_panel(tab_volk):
                    build_volk()

        # 3. Подвал (Лог)
        build_log_terminal()

    # Восстанавливаем последний активный таб (защита от reset при reconnect)
    _last_tab = app.storage.user.get("last_tab", "AI ЧАТ" if not is_admin else "ОБЗОР")
    _tab_map = {"AI ЧАТ": tab_chat}
    if is_admin:
        _tab_map.update({
            "ОБЗОР":          tab_overview,
            "С.А.М.О.В.А.Р.": tab_samovar,
            "П.Р.О.Р.А.Б.":   tab_prorab,
            "ГРАФ":            tab_mermaid,
            "🔬 ДИАГНОСТИКА":  tab_diag,
            "В.О.Л.К.":       tab_volk,
        })
    _target = _tab_map.get(_last_tab)
    if _target and _target != _default_tab:
        ui.timer(0.0, lambda t=_target: tabs.set_value(t), once=True)



if __name__ in {"__main__", "__mp_main__"}:
    # Фоновые задачи запускаем при старте UI
    app.on_startup(lambda: asyncio.create_task(bg_loop()))
    
    ui.run(
        port=UI_PORT,
        title="Л.Е.С. v5.0",
        dark=True,
        show=False,
        storage_secret="les_secret_883",
        reload=False,
        reconnect_timeout=10,   # NiceGUI 3.12: ждать 10с перед hard reload
    )
