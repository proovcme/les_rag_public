"""
С.О.В.У.Ш.К.А. v5.0 — Шапка (Header) со встроенными табами
"""
from __future__ import annotations

import asyncio
from nicegui import app, ui

from backend.auth import logout
from sovushka.components.charts import _html
from sovushka.state import last_api_error_text


def build_header(
    is_admin: bool,
    auth_role: str,
    auth_holder: str,
    *,
    admin_tabs: bool | None = None,
    include_chat: bool = True,
    admin_link: bool = False,
    chat_link: bool = False,
):
    """
    Строит единую sticky-полосу: [лого] [табы] [контролы].
    Возвращает (tabs, tab_objects_dict) — используется в sovushka_ng.py для tab_panels.
    """

    tab_refs = {}
    show_admin_tabs = is_admin if admin_tabs is None else admin_tabs

    with ui.element("header").classes("w-full").style(
        "position:sticky;top:0;z-index:999;"
        "background:var(--bg-panel);border-bottom:1px solid var(--border);"
        "display:flex;align-items:center;padding:0 16px;height:44px;gap:0;"
    ):
        # ── Лого ──────────────────────────────────────────────────────────────
        _html(
            '<span class="les-brand" style="white-space:nowrap;margin-right:16px;">'
            '[O_O] Л.Е.С.</span>'
        )

        # ── Табы (по центру, растягиваются) ───────────────────────────────────
        with ui.tabs().style(
            "flex:1;min-width:0;background:transparent;border:none;"
            "font-family:var(--font);font-size:.65rem;font-weight:700;"
            "color:var(--dim);height:44px;"
        ) as tabs:
            if show_admin_tabs:
                tab_refs["overview"] = ui.tab("ОБЗОР",          icon="o_dashboard")
                tab_refs["samovar"]  = ui.tab("С.А.М.О.В.А.Р.", icon="o_inventory_2")
                tab_refs["prorab"]   = ui.tab("П.Р.О.Р.А.Б.",   icon="o_monitor")
            if include_chat:
                tab_refs["chat"]     = ui.tab("AI ЧАТ",         icon="o_forum")
                tab_refs["history"]  = ui.tab("ИСТОРИЯ",        icon="o_history")
            if show_admin_tabs:
                tab_refs["mermaid"]  = ui.tab("ГРАФ",           icon="o_account_tree")
                tab_refs["diag"]     = ui.tab("🔬 ДИАГН",       icon="o_medical_services")
                tab_refs["volk"]     = ui.tab("В.О.Л.К.",       icon="o_vpn_key")

        # ── Контролы (справа) ─────────────────────────────────────────────────
        with ui.row().classes("items-center gap-1").style("flex-shrink:0;margin-left:8px;"):

            # Обновить
            ui.button("↻", on_click=lambda: asyncio.create_task(_full_refresh())
            ).props("flat dense").style("color:var(--dim);font-size:.85rem;")

            # Тема
            _DARK_VARS  = ["#050608","#10141b","#18212c","#f8fbff",
                           "#d2deea","#55708a","#38bdf8","#22e06f","#ff6b6b","#ffd166","#c084fc"]
            _LIGHT_VARS = ["#f7fafc","#ffffff","#e6edf5","#0d1117",
                           "#263544","#8aa2b8","#005fcc","#007a3d","#b4232a","#8a5400","#7c3aed"]
            _CSS_KEYS   = ["--bg","--bg-panel","--bg-mod","--text","--dim",
                           "--border","--accent","--ok","--err","--warn","--pauk"]

            _dark_init = app.storage.user.get("dark_theme", True)

            def _toggle_theme():
                d = not app.storage.user.get("dark_theme", True)
                app.storage.user["dark_theme"] = d
                vs = _DARK_VARS if d else _LIGHT_VARS
                js = ";".join(
                    f"document.documentElement.style.setProperty('{k}','{v}')"
                    for k, v in zip(_CSS_KEYS, vs)
                )
                js += f";document.body.style.background='{vs[0]}';document.body.style.color='{vs[3]}';"
                js += f";if(window.Quasar){{Quasar.Dark.set({'true' if d else 'false'});}}"
                ui.run_javascript(js)
                theme_btn.set_text("🌙" if d else "☀")

            theme_btn = ui.button(
                "🌙" if _dark_init else "☀", on_click=_toggle_theme
            ).props("flat dense").style("color:var(--dim);font-size:.85rem;")

            if not _dark_init:
                ui.timer(0.0, lambda: ui.run_javascript(
                    "if(window.Quasar){Quasar.Dark.set(false);}"
                ), once=True)

            if is_admin:
                if chat_link:
                    ui.button("ЧАТ", on_click=lambda: ui.navigate.to("/")).props(
                        "flat no-caps dense"
                    ).style("color:var(--accent);font-size:.62rem;font-family:var(--font);")

                if admin_link:
                    ui.button("АДМИНКА", on_click=lambda: ui.navigate.to("/les")).props(
                        "flat no-caps dense"
                    ).style("color:var(--accent);font-size:.62rem;font-family:var(--font);")

                # Настройки
                with ui.dialog() as settings_dialog, ui.card().style(
                    "background:var(--bg-panel);border:1px solid var(--border);min-width:480px;padding:24px;"
                ):
                    ui.label("⚙ НАСТРОЙКИ Л.Е.С.").style(
                        "font-size:.95rem;font-weight:900;margin-bottom:16px;"
                    )
                    set_llm   = ui.input("LLM Модель",        value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_embed = ui.input("Embedding Модель",  value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_url   = ui.input("MLX URL",  value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")

                    async def _load_settings():
                        from sovushka.state import api_get
                        d = await api_get("/api/settings")
                        if d:
                            set_llm.set_value(d.get("llm_model", ""))
                            set_embed.set_value(d.get("embed_model", ""))
                            set_url.set_value(d.get("mlx_url", ""))

                    ui.timer(0.1, lambda: asyncio.create_task(_load_settings()), once=True)
                    ui.separator().style("border-color:var(--border);margin:12px 0;")
                    ui.label("⚠ Опасная зона").style("color:var(--err);font-size:.65rem;font-weight:900;text-transform:uppercase;")

                    async def _reset_all():
                        ok = await ui.run_javascript("confirm('Сбросить ВСЕ датасеты? Необратимо!')")
                        if ok:
                            from sovushka.state import api_delete, refresh_samovar
                            d = await api_delete("/api/rag/datasets")
                            if d:
                                ui.notify(f"Сброс: {d}", type="warning")
                                await refresh_samovar()
                            else:
                                ui.notify(last_api_error_text("Ошибка сброса датасетов"), type="negative")

                    ui.button("☢ Сбросить ВСЕ датасеты", on_click=_reset_all).props("no-caps").style(
                        "border:1px solid var(--err);color:var(--err);background:transparent;margin-top:8px;"
                    )
                    with ui.row().classes("justify-end gap-2 mt-4"):
                        ui.button("Отмена", on_click=settings_dialog.close).props("no-caps flat").style("color:var(--dim);")

                        async def save_settings():
                            from sovushka.state import api_post, add_log
                            d = await api_post("/api/settings?restart=true", {
                                "llm_model":   set_llm.value,
                                "embed_model": set_embed.value,
                                "mlx_url":     set_url.value,
                            })
                            if d:
                                add_log(f"[SETTINGS] Сохранено: LLM={set_llm.value}")
                                ui.notify("Настройки сохранены", type="positive")
                                settings_dialog.close()
                            else:
                                ui.notify(last_api_error_text("Ошибка сохранения настроек"), type="negative")

                        ui.button("💾 Сохранить", on_click=save_settings).props("no-caps").style(
                            "border:1px solid var(--accent);color:var(--accent);background:transparent;"
                        )

                ui.button("⚙", on_click=lambda: settings_dialog.open()).props("flat dense").style("color:var(--dim);")

            # Пользователь / выход
            badge_text = f"{'👑' if is_admin else '👤'} {auth_holder or auth_role}"
            ui.button(badge_text, on_click=lambda: (logout(), ui.navigate.to("/login"))
            ).props("flat no-caps dense").style(
                "color:var(--ok);font-size:.62rem;font-family:var(--font);max-width:120px;"
                "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
            )

    return tabs, tab_refs


# ── Приватные функции ─────────────────────────────────────────────────────────

async def _full_refresh():
    from sovushka.state import refresh_metrics, refresh_status, refresh_mlx, refresh_samovar, add_log
    add_log("[REFRESH] Полное обновление...")
    await asyncio.gather(refresh_metrics(), refresh_status(), refresh_mlx(), refresh_samovar())
    add_log("[REFRESH] Готово.")
