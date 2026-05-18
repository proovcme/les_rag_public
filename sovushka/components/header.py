"""
С.О.В.У.Ш.К.А. v5.0 — Шапка (Header)
"""
from __future__ import annotations

import asyncio
from nicegui import app, ui

from backend.auth import logout
from sovushka.components.charts import _html


def build_header(tabs, auth_role: str, auth_holder: str, is_admin: bool):
    """Строит sticky header. Вызывать внутри @ui.page("/")."""

    with ui.element("header").classes("les-header w-full").style(
        "position:sticky;top:0;z-index:999;"
    ):
        with ui.row().classes("items-center gap-3"):
            _html('<span class="les-brand">[O_O] С.О.В.У.Ш.К.А.</span>')
            ui.label("v5.0 · NiceGUI").style(
                "font-size:.65rem;color:var(--dim);font-weight:700;"
            )

        with ui.row().classes("items-center gap-2"):
            # Кнопка режима РАГ / КОД
            mode_btn = ui.button(
                "РАГ",
                on_click=lambda: asyncio.create_task(_toggle_mode(mode_btn))
            ).classes("mode-rag")
            mode_btn.props("no-caps flat")

            # Кнопка обновить
            ui.button(
                "↻",
                on_click=lambda: asyncio.create_task(_full_refresh())
            ).props("flat").style("color:var(--dim);")

            # Переключатель темы
            _DARK_VARS  = ["#08090b", "#12151a", "#1a1e25", "#ffffff",
                           "#94a3b8", "#2d3748", "#3b82f6", "#10b981", "#ef4444", "#f59e0b", "#8b5cf6"]
            _LIGHT_VARS = ["#f6f8fa", "#ffffff", "#eaeef2", "#1f2328",
                           "#424a53", "#d0d7de", "#0969da", "#1a7f37", "#cf222e", "#9a6700", "#8250df"]
            _CSS_KEYS   = ["--bg", "--bg-panel", "--bg-mod", "--text", "--dim",
                           "--border", "--accent", "--ok", "--err", "--warn", "--pauk"]

            def _apply_theme_js(dark: bool) -> str:
                vs = _DARK_VARS if dark else _LIGHT_VARS
                js = ";".join(
                    f"document.documentElement.style.setProperty('{k}','{v}')"
                    for k, v in zip(_CSS_KEYS, vs)
                )
                js += f";document.body.style.background='{vs[0]}';document.body.style.color='{vs[3]}';"
                return js

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

            theme_btn = ui.button("🌙" if _dark_init else "☀", on_click=_toggle_theme).props("flat").style(
                "color:var(--dim);font-size:.85rem;"
            )

            # Восстанавливаем тему при реконнекте WebSocket (если была светлая)
            if not _dark_init:
                ui.timer(0.1, lambda: ui.run_javascript(_apply_theme_js(False)), once=True)

            # Диалог настроек
            with ui.dialog() as settings_dialog, ui.card().style(
                "background:var(--bg-panel);border:1px solid var(--border);min-width:480px;padding:24px;"
            ):
                ui.label("⚙ НАСТРОЙКИ Л.Е.С.").style(
                    "font-size:.95rem;font-weight:900;margin-bottom:16px;"
                )

                set_llm = ui.input("LLM Модель", value="").style(
                    "background:var(--bg);color:var(--text);font-family:var(--font);width:100%;"
                )
                set_embed = ui.input("Embedding Модель", value="").style(
                    "background:var(--bg);color:var(--text);font-family:var(--font);width:100%;"
                )
                set_url = ui.input("Ollama / MLX URL", value="").style(
                    "background:var(--bg);color:var(--text);font-family:var(--font);width:100%;"
                )

                async def _load_settings():
                    from sovushka.state import api_get
                    d = await api_get("/api/settings")
                    if d:
                        set_llm.set_value(d.get("llm_model", ""))
                        set_embed.set_value(d.get("embed_model", ""))
                        set_url.set_value(d.get("ollama_url", ""))

                ui.timer(0.1, lambda: asyncio.create_task(_load_settings()), once=True)

                ui.separator().style("border-color:var(--border);margin:12px 0;")
                ui.label("⚠ Опасная зона").style(
                    "color:var(--err);font-size:.65rem;font-weight:900;text-transform:uppercase;"
                )

                async def _reset_all():
                    ok = await ui.run_javascript("confirm('Сбросить ВСЕ датасеты? Необратимо!')")
                    if ok:
                        from sovushka.state import api_delete, refresh_samovar
                        d = await api_delete("/api/rag/datasets")
                        ui.notify(f"Сброс: {d}", type="warning") if d else None
                        await refresh_samovar()

                ui.button("☢ Сбросить ВСЕ датасеты", on_click=_reset_all).props("no-caps").style(
                    "border:1px solid var(--err);color:var(--err);background:transparent;margin-top:8px;"
                )

                with ui.row().classes("justify-end gap-2 mt-4"):
                    ui.button("Отмена", on_click=settings_dialog.close).props("no-caps flat").style(
                        "color:var(--dim);"
                    )

                    async def save_settings():
                        from sovushka.state import api_post, add_log
                        d = await api_post("/api/settings", {
                            "llm_model":  set_llm.value,
                            "embed_model": set_embed.value,
                            "ollama_url":  set_url.value,
                        })
                        add_log(f"[SETTINGS] Сохранено: LLM={set_llm.value}")
                        ui.notify("Настройки сохранены, прокси перезапускается...", type="positive")
                        settings_dialog.close()

                    ui.button("💾 Сохранить", on_click=save_settings).props("no-caps").style(
                        "border:1px solid var(--accent);color:var(--accent);background:transparent;"
                    )

            ui.button("⚙", on_click=lambda: settings_dialog.open()).props("flat").style(
                "color:var(--dim);"
            )

            # В.О.Л.К. badge — имя + выход
            badge_text = f"{'👑' if is_admin else '👤'} {auth_holder or auth_role}"
            ui.button(
                badge_text,
                on_click=lambda: (logout(), ui.navigate.to("/login"))
            ).props("flat no-caps").style(
                "color:var(--ok);font-size:.65rem;font-family:var(--font);"
            )


# ── Приватные функции хедера ──────────────────────────────────────────────────

async def _toggle_mode(btn):
    from sovushka.state import state, api_post, add_log
    from sovushka.config import MLX_URL

    next_mode = "code" if state["mode"] == "rag" else "rag"
    next_model = "mlx-community/Qwen3-14B-4bit"
    btn.set_text("...")
    add_log(f"[РЕЖИМ] Переключение → {next_mode.upper()}")
    try:
        await api_post("/api/mode", {"mode": next_mode, "model": next_model})
        try:
            await api_post(
                "/api/switch_model",
                {"model": next_model, "mode": next_mode},
                base=MLX_URL
            )
            add_log(f"[MLX] switch_model → {next_model}")
        except Exception as e:
            add_log(f"[MLX] switch_model недоступен: {e}")
        state["mode"] = next_mode
        if next_mode == "code":
            btn.set_text("КОД")
            btn.classes(remove="mode-rag", add="mode-code")
        else:
            btn.set_text("РАГ")
            btn.classes(remove="mode-code", add="mode-rag")
        add_log(f"[РЕЖИМ] {next_mode.upper()} активен.")
    except Exception as e:
        add_log(f"[РЕЖИМ] Ошибка: {e}")
        btn.set_text("РАГ" if state["mode"] == "rag" else "КОД")


async def _full_refresh():
    from sovushka.state import refresh_metrics, refresh_status, refresh_mlx, refresh_samovar, add_log
    add_log("[REFRESH] Полное обновление...")
    await asyncio.gather(
        refresh_metrics(),
        refresh_status(),
        refresh_mlx(),
        refresh_samovar(),
    )
    add_log("[REFRESH] Готово.")
