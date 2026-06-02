"""
С.О.В.У.Ш.К.А. v5.0 — Шапка (Header) со встроенными табами
"""
from __future__ import annotations

import asyncio
import json
from nicegui import app, ui

from backend.auth import logout
from sovushka.components.charts import _html
from sovushka.state import last_api_error_text
from sovushka.styles import _DARK_THEME, _LIGHT_THEME


def build_header(
    is_admin: bool,
    auth_role: str,
    auth_holder: str,
    *,
    admin_tabs: bool | None = None,
    include_chat: bool = True,
    admin_link: bool = False,
    chat_link: bool = False,
    visualizer_url: str | None = None,
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
        "display:flex;align-items:center;padding:0 16px;height:56px;gap:0;"
    ):
        # ── Лого ──────────────────────────────────────────────────────────────
        _html(
            '<span class="les-brand" style="white-space:nowrap;margin-right:16px;">'
            '[O_O] Л.Е.С.</span>'
        )

        # ── Табы (по центру, растягиваются) ───────────────────────────────────
        with ui.tabs().classes("les-top-tabs").props("dense no-caps").style(
            "flex:1;min-width:0;background:transparent;border:none;"
            "font-family:var(--font);font-size:.65rem;font-weight:700;"
            "color:var(--dim);height:56px;"
        ) as tabs:
            if show_admin_tabs:
                tab_refs["overview"] = ui.tab("ОБЗОР",          icon="o_dashboard")
                tab_refs["samovar"]  = ui.tab("С.А.М.О.В.А.Р.", icon="o_inventory_2")
                tab_refs["prorab"]   = ui.tab("П.Р.О.Р.А.Б.",   icon="o_monitor")
            if include_chat:
                tab_refs["chat"]     = ui.tab("AI ЧАТ",         icon="o_forum")
                tab_refs["history"]  = ui.tab("ИСТОРИЯ",        icon="o_history")
            if show_admin_tabs:
                tab_refs["qdrant_viz"] = ui.tab("КВАДРАНТ",      icon="o_scatter_plot")
                tab_refs["diag"]     = ui.tab("Д.И.А.Г.Н.О.З.", icon="o_health_and_safety")
                tab_refs["volk"]     = ui.tab("В.О.Л.К.",       icon="o_vpn_key")

        # ── Контролы (справа) ─────────────────────────────────────────────────
        with ui.row().classes("items-center gap-1").style("flex-shrink:0;margin-left:8px;"):

            # Обновить
            ui.button("↻", on_click=lambda: asyncio.create_task(_full_refresh())
            ).props("flat dense").style("color:var(--dim);font-size:.85rem;")

            # Тема
            _dark_init = app.storage.user.get("dark_theme", True)

            def _toggle_theme():
                d = not app.storage.user.get("dark_theme", True)
                app.storage.user["dark_theme"] = d
                vars_ = _DARK_THEME if d else _LIGHT_THEME
                js = ";".join(
                    f"document.documentElement.style.setProperty({json.dumps(k)},{json.dumps(v)})"
                    for k, v in vars_.items()
                )
                js += (
                    f";document.body.style.background={json.dumps(vars_['--bg'])};"
                    f"document.body.style.color={json.dumps(vars_['--text'])};"
                )
                js += f";if(window.Quasar){{Quasar.Dark.set({'true' if d else 'false'});}}"
                ui.run_javascript(js)
                theme_btn.set_text("🌙" if d else "☀")

            theme_btn = ui.button(
                "🌙" if _dark_init else "☀", on_click=_toggle_theme
            ).props("flat dense").style("color:var(--dim);font-size:.85rem;")

            if not _dark_init:
                ui.run_javascript("if(window.Quasar){Quasar.Dark.set(false);}")

            if is_admin:
                if chat_link:
                    ui.button("ЧАТ", on_click=lambda: ui.navigate.to("/")).props(
                        "flat no-caps dense"
                    ).style("color:var(--accent);font-size:.62rem;font-family:var(--font);")

                if admin_link:
                    ui.button("АДМИНКА", on_click=lambda: ui.navigate.to("/les")).props(
                        "flat no-caps dense"
                    ).style("color:var(--accent);font-size:.62rem;font-family:var(--font);")

                if visualizer_url:
                    ui.link("КВАДРАНТ ↗", target=visualizer_url, new_tab=True).classes(
                        "no-underline"
                    ).style(
                        "color:var(--accent);font-size:.62rem;font-family:var(--font);"
                        "font-weight:700;white-space:nowrap;padding:4px 6px;"
                    )

                # Настройки
                with ui.dialog() as settings_dialog, ui.card().style(
                    "background:var(--bg-panel);border:1px solid var(--border);min-width:640px;padding:24px;"
                ):
                    ui.label("⚙ НАСТРОЙКИ Л.Е.С.").style(
                        "font-size:.95rem;font-weight:900;margin-bottom:16px;"
                    )
                    set_llm   = ui.input("LLM Модель",        value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_embed = ui.input("Embedding Модель",  value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_url   = ui.input("MLX URL",  value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    ui.separator().style("border-color:var(--border);margin:12px 0;")
                    ui.label("Speckle BIM/CAD").style("color:var(--dim);font-size:.65rem;font-weight:900;text-transform:uppercase;")
                    set_speckle_enabled = ui.checkbox("Speckle enabled", value=True).style("color:var(--text);font-family:var(--font);")
                    set_speckle_url = ui.input("Speckle Base URL", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_speckle_graphql = ui.input("Speckle GraphQL URL", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_speckle_token = ui.input("Speckle API Token", value="", password=True, password_toggle_button=True).style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_speckle_clear = ui.checkbox("Сбросить Speckle token", value=False).style("color:var(--text);font-family:var(--font);")
                    set_speckle_timeout = ui.number("Wake timeout sec", value=5, min=0.5, max=60, step=0.5, format="%.1f").style("background:var(--bg);color:var(--text);font-family:var(--font);width:180px;")
                    ui.separator().style("border-color:var(--border);margin:12px 0;")
                    ui.label("External providers").style("color:var(--dim);font-size:.65rem;font-weight:900;text-transform:uppercase;")
                    set_openrouter_url = ui.input("OpenRouter Base URL", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_openrouter_model = ui.input("OpenRouter Model", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_openrouter_key = ui.input("OpenRouter API Key", value="", password=True, password_toggle_button=True).style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_openrouter_clear = ui.checkbox("Сбросить OpenRouter key", value=False).style("color:var(--text);font-family:var(--font);")
                    set_openai_url = ui.input("OpenAI-compatible Base URL", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_openai_model = ui.input("OpenAI-compatible Model", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_openai_key = ui.input("OpenAI-compatible API Key", value="", password=True, password_toggle_button=True).style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_openai_clear = ui.checkbox("Сбросить OpenAI-compatible key", value=False).style("color:var(--text);font-family:var(--font);")
                    ui.separator().style("border-color:var(--border);margin:12px 0;")
                    ui.label("Е.Ж.И.К. IMAP").style("color:var(--dim);font-size:.65rem;font-weight:900;text-transform:uppercase;")
                    with ui.row().classes("w-full gap-2"):
                        set_mail_host = ui.input("IMAP Host", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);flex:1;")
                        set_mail_port = ui.number("Port", value=993, min=1, max=65535, step=1, format="%.0f").style("background:var(--bg);color:var(--text);font-family:var(--font);width:120px;")
                        set_mail_ssl = ui.checkbox("SSL", value=True).style("color:var(--text);font-family:var(--font);")
                    set_mail_login = ui.input("Login", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_mail_password = ui.input("Password / app password", value="", password=True, password_toggle_button=True).style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_mail_folders = ui.input("Folders", value="INBOX").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_mail_ocr = ui.checkbox("OCR вложений", value=True).style("color:var(--text);font-family:var(--font);")

                    def _yandex_mail_preset():
                        set_mail_host.set_value("imap.yandex.ru")
                        set_mail_port.set_value(993)
                        set_mail_ssl.set_value(True)
                        if not set_mail_folders.value:
                            set_mail_folders.set_value("INBOX")

                    ui.button("Yandex preset", on_click=_yandex_mail_preset).props("no-caps flat").style(
                        "border:1px solid var(--border);color:var(--accent);background:transparent;"
                    )

                    async def _load_settings():
                        from sovushka.state import api_get
                        d = await api_get("/api/settings")
                        if d:
                            set_llm.set_value(d.get("llm_model", ""))
                            set_embed.set_value(d.get("embed_model", ""))
                            set_url.set_value(d.get("mlx_url", ""))
                            speckle = d.get("speckle") or {}
                            set_speckle_enabled.set_value(bool(speckle.get("enabled", True)))
                            set_speckle_url.set_value(speckle.get("base_url", "https://speckle.ovc.me"))
                            set_speckle_graphql.set_value(speckle.get("graphql_url", "https://speckle.ovc.me/graphql"))
                            set_speckle_token.set_value("")
                            set_speckle_token.props(
                                f"placeholder=\"{'token уже задан; оставь пустым, чтобы не менять' if speckle.get('api_token_set') else 'Speckle API token'}\""
                            )
                            set_speckle_clear.set_value(False)
                            set_speckle_timeout.set_value(float(speckle.get("wake_timeout_sec", 5) or 5))
                            providers = d.get("providers") or {}
                            openrouter = providers.get("openrouter") or {}
                            openai = providers.get("openai_compatible") or {}
                            set_openrouter_url.set_value(openrouter.get("base_url", "https://openrouter.ai/api/v1"))
                            set_openrouter_model.set_value(openrouter.get("model", ""))
                            set_openrouter_key.set_value("")
                            set_openrouter_key.props(
                                f"placeholder=\"{'key уже задан; оставь пустым, чтобы не менять' if openrouter.get('api_key_set') else 'OpenRouter API key'}\""
                            )
                            set_openrouter_clear.set_value(False)
                            set_openai_url.set_value(openai.get("base_url", ""))
                            set_openai_model.set_value(openai.get("model", ""))
                            set_openai_key.set_value("")
                            set_openai_key.props(
                                f"placeholder=\"{'key уже задан; оставь пустым, чтобы не менять' if openai.get('api_key_set') else 'OpenAI-compatible API key'}\""
                            )
                            set_openai_clear.set_value(False)
                            mail = d.get("mail") or {}
                            set_mail_host.set_value(mail.get("imap_host", ""))
                            set_mail_port.set_value(mail.get("imap_port", 993))
                            set_mail_ssl.set_value(bool(mail.get("imap_ssl", True)))
                            set_mail_login.set_value(mail.get("imap_login", ""))
                            set_mail_password.set_value("")
                            set_mail_password.props(
                                f"placeholder=\"{'пароль уже задан; оставь пустым, чтобы не менять' if mail.get('imap_password_set') else 'пароль приложения Яндекс'}\""
                            )
                            set_mail_folders.set_value(mail.get("imap_folders", "INBOX"))
                            set_mail_ocr.set_value(bool(mail.get("attachment_ocr_enabled", True)))

                    asyncio.create_task(_load_settings())
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
                            payload = {
                                "llm_model":   set_llm.value,
                                "embed_model": set_embed.value,
                                "mlx_url":     set_url.value,
                                "speckle_enabled": bool(set_speckle_enabled.value),
                                "speckle_base_url": set_speckle_url.value or "",
                                "speckle_graphql_url": set_speckle_graphql.value or "",
                                "speckle_api_token": set_speckle_token.value or None,
                                "speckle_api_token_clear": bool(set_speckle_clear.value),
                                "speckle_wake_timeout_sec": float(set_speckle_timeout.value or 5),
                                "openrouter_base_url": set_openrouter_url.value or "",
                                "openrouter_model": set_openrouter_model.value or "",
                                "openrouter_api_key": set_openrouter_key.value or None,
                                "openrouter_api_key_clear": bool(set_openrouter_clear.value),
                                "openai_base_url": set_openai_url.value or "",
                                "openai_model": set_openai_model.value or "",
                                "openai_api_key": set_openai_key.value or None,
                                "openai_api_key_clear": bool(set_openai_clear.value),
                                "mail_imap_host": set_mail_host.value or "",
                                "mail_imap_port": int(set_mail_port.value or 993),
                                "mail_imap_ssl": bool(set_mail_ssl.value),
                                "mail_imap_login": set_mail_login.value or "",
                                "mail_imap_password": set_mail_password.value or None,
                                "mail_imap_folders": set_mail_folders.value or "INBOX",
                                "mail_attachment_ocr_enabled": bool(set_mail_ocr.value),
                            }
                            d = await api_post("/api/settings", payload)
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
