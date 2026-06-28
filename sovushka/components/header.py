"""
С.О.В.У.Ш.К.А. v5.0 — Шапка (Header) со встроенными табами
"""
from __future__ import annotations

import asyncio
import json
from nicegui import app, ui

from backend.auth import logout
from sovushka.components.charts import _html
from sovushka.state import api_get, last_api_error_text, proxy_online
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
        with ui.row().classes("items-center").style("gap:6px;margin-right:12px;white-space:nowrap;flex-wrap:nowrap;"):
            ui.icon("o_forest").style("font-size:21px;color:var(--accent);")
            ui.label("Л.Е.С.").classes("les-brand")

        # ── Бейдж версии (v0.19): что реально запущено — версия+commit+runtime-divergence ──
        _ver_state: dict = {"info": None}
        ver_badge = ui.button("· · ·").props("flat dense no-caps").style(
            "color:var(--dim);font-family:var(--font);font-size:.58rem;font-weight:700;"
            "margin-right:14px;padding:2px 7px;border:1px solid var(--border);border-radius:5px;"
            "min-height:0;line-height:1.2;"
        ).tooltip("Версия ЛЕС — нажмите для деталей")

        def _ver_rows(info: dict) -> list[tuple[str, str]]:
            al = info.get("runtime_alignment") or {}
            fl = info.get("feature_flags") or {}
            ds = info.get("deploy_stamp") or {}
            ds_line = ds.get("status", "unknown")
            if ds.get("hash_mismatch_files"):
                ds_line += " · изменены: " + ", ".join(ds["hash_mismatch_files"])
            return [
                ("Версия ЛЕС", info.get("app_version", "?")),
                ("Harness", info.get("harness_version", "?")),
                ("Git commit", f"{info.get('git_commit','?')} ({info.get('git_branch','?')})"),
                ("Deployed commit", info.get("deployed_commit", "?")),
                ("Deploy stamp", ds_line),
                ("Deployed at", ds.get("deployed_at", "?")),
                ("Build", info.get("build_time", "?")),
                ("Runtime", info.get("runtime_path", "?")),
                ("Evidence schema", info.get("evidence_schema_version", "?")),
                ("Extraction", info.get("extraction_schema_version", "?")),
                ("Runtime alignment", al.get("status", "unknown")
                 + ((" · изменены: " + ", ".join(al.get("changed_files") or [])) if al.get("changed_files") else "")),
                ("Unified harness", "ON" if fl.get("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED") else "OFF"),
                ("Sidecar write", "ON" if fl.get("LES_ALLOW_RUNTIME_SIDECAR_WRITE") else "OFF"),
            ]

        def _open_version_dialog() -> None:
            info = _ver_state["info"] or {}
            with ui.dialog() as dlg, ui.card().style(
                "background:var(--bg-panel);border:1px solid var(--border);min-width:440px;padding:18px;"
            ):
                ui.label("Версия и сборка ЛЕС").style("font-weight:900;font-size:.85rem;margin-bottom:6px;")
                if not info:
                    ui.label("Версия недоступна (прокси не ответил на /api/version).").style(
                        "color:var(--warn);font-size:.7rem;")
                else:
                    al = info.get("runtime_alignment") or {}
                    if al.get("status") == "divergent":
                        ui.label("⚠ Runtime отличается от репозитория").style(
                            "color:var(--warn);font-size:.66rem;font-family:var(--font);margin-bottom:4px;")
                    for k, v in _ver_rows(info):
                        with ui.row().style("gap:8px;align-items:baseline;width:100%;"):
                            ui.label(k).style("color:var(--dim);font-size:.62rem;min-width:140px;")
                            ui.label(str(v)).style("font-size:.66rem;font-family:var(--font);")
                    ui.button("Копировать диагностику", on_click=lambda: ui.run_javascript(
                        f"navigator.clipboard.writeText({json.dumps(json.dumps(info, ensure_ascii=False, indent=2))})"
                    )).props("flat dense no-caps").style("color:var(--accent);font-size:.62rem;margin-top:8px;")
            dlg.open()

        ver_badge.on("click", lambda: _open_version_dialog())

        async def _load_version() -> None:
            info = await api_get("/api/version")
            if isinstance(info, dict):
                _ver_state["info"] = info
                # бейдж ведёт с DEPLOYED commit (что реально запущено), git рантайма отстаёт при cp-деплое
                c = info.get("deployed_commit") or info.get("git_commit", "")
                h = info.get("harness_version", "")
                ver_badge.set_text(f"{info.get('app_version','?')}" + (f" · h{h}" if h else "")
                                   + (f" · {c}" if c and c != "unknown" else ""))
                al = (info.get("runtime_alignment") or {}).get("status")
                ds = (info.get("deploy_stamp") or {}).get("status")
                if al == "divergent" or ds in ("stale", "deploy_stamp_missing"):
                    ver_badge.style("color:var(--warn);border-color:var(--warn);")
            else:
                ver_badge.set_text("?")

        ui.timer(0.4, _load_version, once=True)

        # ── Табы (по центру, растягиваются) ───────────────────────────────────
        with ui.tabs().classes("les-top-tabs").props("dense no-caps").style(
            "flex:1;min-width:0;background:transparent;border:none;"
            "font-family:var(--font);font-size:.65rem;font-weight:700;"
            "color:var(--dim);height:56px;"
        ) as tabs:
            if show_admin_tabs:
                # v0.24: админка с чистыми именами; рабочие инструменты оставляем видимыми,
                # иначе оператор не видит служебные источники, ВОР и нормоконтроль.
                tab_refs["diag"]       = ui.tab("Состояние", icon="o_health_and_safety")
                tab_refs["samovar"]    = ui.tab("Датасеты",  icon="o_inventory_2")
                tab_refs["instrumenty"] = ui.tab("Инструменты", icon="o_build")
                tab_refs["qdrant_viz"] = ui.tab("Визуал",    icon="o_scatter_plot")
                tab_refs["volk"]       = ui.tab("Доступ",    icon="o_vpn_key")  # В.О.Л.К. — контур доступа
            if include_chat:
                tab_refs["chat"]     = ui.tab("AI ЧАТ",         icon="o_forum")
                tab_refs["history"]  = ui.tab("ИСТОРИЯ",        icon="o_history")

        # ── Контролы (справа) ─────────────────────────────────────────────────
        with ui.row().classes("items-center gap-1").style("flex-shrink:0;margin-left:8px;"):

            # W5.3: индикатор доступности proxy (зелёный — на связи, красный — нет)
            proxy_dot = ui.icon("circle").style("font-size:.6rem;color:#10b981;margin:0 2px;")
            proxy_dot.tooltip("связь с proxy")

            def _upd_proxy_dot():
                proxy_dot.style(
                    f"font-size:.6rem;color:{'#10b981' if proxy_online() else '#ef4444'};margin:0 2px;"
                )

            ui.timer(3.0, _upd_proxy_dot)

            # Обновить
            ui.button(icon="o_refresh", on_click=lambda: asyncio.create_task(_full_refresh())
            ).props('flat dense round aria-label="Обновить данные"').style("color:var(--dim);")

            # Тема
            if app.storage.user.get("theme_default_migrated") != "0.24-light-2":
                app.storage.user["dark_theme"] = False
                app.storage.user["theme_default_migrated"] = "0.24-light-2"
            _dark_init = app.storage.user.get("dark_theme", False)

            def _toggle_theme():
                d = not app.storage.user.get("dark_theme", False)
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
                theme_btn.props(f'icon={"o_dark_mode" if d else "o_light_mode"}')

            theme_btn = ui.button(
                icon=("o_dark_mode" if _dark_init else "o_light_mode"), on_click=_toggle_theme
            ).props('flat dense round aria-label="Переключить тему"').style("color:var(--dim);")

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
                        "font-size:.95rem;font-weight:900;margin-bottom:8px;"
                    )
                    # Однозначный ответ «какая модель отвечает» — всегда наверху диалога.
                    answering_label = ui.label("СЕЙЧАС ОТВЕЧАЕТ: …").style(
                        "font-size:.8rem;font-weight:900;color:var(--ok);border:1px solid var(--border);"
                        "border-left:3px solid var(--ok);border-radius:6px;padding:8px 12px;width:100%;"
                        "background:var(--bg);margin-bottom:8px;"
                    )
                    # Режим работы — пресет (local/cloud/mix): один переключатель всего стека
                    # (чат-LLM + скан-OCR + приёмка ИД). Действует сразу, без рестарта.
                    mode_label = ui.label("РЕЖИМ: …").style(
                        "font-size:.72rem;font-weight:900;color:var(--accent);margin-bottom:4px;"
                    )

                    async def _apply_preset(name: str):
                        from sovushka.state import api_post
                        r = await api_post("/api/settings/preset", {"name": name})
                        if r and r.get("preset"):
                            a = r.get("applied", {})
                            ui.notify(f"Режим: {r['preset']} (чат {a.get('LES_LLM_PROVIDER','?')}, "
                                      f"OCR {a.get('RAG_OCR_BACKEND','?')}, ИД {a.get('LES_ASBUILT_OCR_ENGINE','?')})",
                                      type="positive")
                            await _load_settings()
                        else:
                            ui.notify("Не удалось переключить режим", type="negative")

                    with ui.row().classes("w-full gap-2").style("margin-bottom:12px;"):
                        ui.button("🖥 Локально", on_click=lambda: _apply_preset("local")).props("no-caps flat").style(
                            "border:1px solid var(--border);color:var(--ok);background:transparent;flex:1;")
                        ui.button("☁ Облако", on_click=lambda: _apply_preset("cloud")).props("no-caps flat").style(
                            "border:1px solid var(--border);color:var(--warn);background:transparent;flex:1;")
                        ui.button("⚖ Микс", on_click=lambda: _apply_preset("mix")).props("no-caps flat").style(
                            "border:1px solid var(--border);color:var(--accent);background:transparent;flex:1;")
                    set_provider = ui.select(
                        {
                            "mlx": "MLX — локальный (валидация Т.О.С.К.А.; блок по памяти активен)",
                            "ollama": "Ollama — локальный (без валидации; блок по памяти активен)",
                            "openrouter": "OpenRouter — ОБЛАКО (без валидации; блок по памяти снят)",
                            "openai": "OpenAI-compatible — ОБЛАКО (без валидации; блок по памяти снят)",
                        },
                        label="Активный LLM-провайдер",
                        value="mlx",
                    ).style("width:100%;font-family:var(--font);")
                    # Локальная модель чата (MLX): лёгкий 4B (основной) ↔ тяжёлый 9B (резерв).
                    # Переключается вживую через /api/settings/mlx-model — без рестарта хоста.
                    _mlx_loading = {"v": False}
                    set_llm = ui.select({}, label="Локальная модель (MLX): 4B быстрый / 9B тяжёлый").props(
                        "dense outlined"
                    ).style("width:100%;font-family:var(--font);")

                    async def _apply_mlx_model(e) -> None:
                        if _mlx_loading["v"]:
                            return
                        model = getattr(e, "value", None) or set_llm.value
                        if not model:
                            return
                        from sovushka.state import api_post, add_log
                        r = await api_post("/api/settings/mlx-model", {"model": model})
                        if r and r.get("status") == "ok":
                            live = "вживую" if r.get("switched_live") else "при следующем старте хоста"
                            add_log(f"[SETTINGS] Локальная модель → {r.get('label', model)} ({live})")
                            ui.notify(f"Локальная модель: {r.get('label', model)} — {live}", type="positive")
                            from sovushka.state import api_get
                            d = await api_get("/api/settings")
                            if d:
                                _refresh_answering(d)
                        else:
                            ui.notify(last_api_error_text("Не удалось переключить локальную модель"), type="negative")

                    set_llm.on_value_change(_apply_mlx_model)
                    set_embed = ui.input("Embedding Модель",  value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_url   = ui.input("MLX URL",  value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_ollama_url = ui.input("Ollama URL", value="http://127.0.0.1:11434").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_ollama_model = ui.input("Ollama Model (например gemma4:12b)", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    ui.separator().style("border-color:var(--border);margin:12px 0;")
                    ui.label("Облачные провайдеры").style("color:var(--dim);font-size:.65rem;font-weight:900;text-transform:uppercase;")
                    set_openrouter_url = ui.input("OpenRouter Base URL", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_openrouter_model = ui.input("OpenRouter Model", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_openrouter_key = ui.input("OpenRouter API Key", value="", password=True, password_toggle_button=True).style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_openrouter_clear = ui.checkbox("Сбросить OpenRouter key", value=False).style("color:var(--text);font-family:var(--font);")
                    set_openai_url = ui.input("OpenAI-compatible Base URL", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_openai_model = ui.input("OpenAI-compatible Model", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_openai_key = ui.input("OpenAI-compatible API Key", value="", password=True, password_toggle_button=True).style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_openai_clear = ui.checkbox("Сбросить OpenAI-compatible key", value=False).style("color:var(--text);font-family:var(--font);")
                    # W3.3/ADR-9: данные по чувствительности. P0 — только локально (MLX),
                    # P1 — можно в облако, P2 — облако ТОЛЬКО при этом согласии. Уровень
                    # датасета ставится в САМОВАРе (колонка «Данные»).
                    set_cloud_consent = ui.checkbox("Разрешить облако для данных P2 (согласие)", value=False).style(
                        "color:var(--warn);font-family:var(--font);font-weight:700;"
                    )
                    _html(
                        '<div class="sov-muted" style="font-size:.6rem;line-height:1.4;">P0 (приватные: НТД по умолчанию, '
                        'почта, договоры) всегда локально на MLX. Уровень датасета — в САМОВАРе → «Данные».</div>'
                    )
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

                    def _refresh_answering(d: dict) -> None:
                        providers = d.get("providers") or {}
                        active = (providers.get("active") or "mlx").lower()
                        llm_fallback = d.get("llm_model") or "(LLM_MODEL из .env)"
                        openrouter_model = (providers.get("openrouter") or {}).get("model") or llm_fallback
                        openai_model = (providers.get("openai_compatible") or {}).get("model") or llm_fallback
                        model_by_provider = {
                            "mlx": llm_fallback,
                            "ollama": (providers.get("ollama") or {}).get("model") or llm_fallback,
                            "openrouter": openrouter_model,
                            "openai": openai_model,
                        }
                        is_cloud = active in ("openrouter", "openai")
                        kind = "ОБЛАКО" if is_cloud else "ЛОКАЛЬНО"
                        answering_label.set_text(
                            f"СЕЙЧАС ОТВЕЧАЕТ: {active.upper()} ({kind}) → {model_by_provider.get(active, '?')}"
                        )
                        color = "var(--warn)" if is_cloud else "var(--ok)"
                        answering_label.style(f"color:{color};border-left:3px solid {color};")

                    async def _load_settings():
                        from sovushka.state import api_get
                        d = await api_get("/api/settings")
                        if d:
                            # MLX-модель: опции из реестра бэкенда + текущая (без триггера свитча).
                            _mlx_loading["v"] = True
                            choices = d.get("mlx_model_choices") or {}
                            cur = d.get("mlx_main_model") or d.get("llm_model") or ""
                            if choices:
                                set_llm.set_options(choices, value=cur if cur in choices else None)
                            _mlx_loading["v"] = False
                            set_embed.set_value(d.get("embed_model", ""))
                            set_url.set_value(d.get("mlx_url", ""))
                            providers = d.get("providers") or {}
                            _refresh_answering(d)
                            try:  # текущий режим-пресет
                                pr = await api_get("/api/settings/presets")
                                cur = (pr or {}).get("current")
                                mode_label.set_text(f"РЕЖИМ: {cur.upper()}" if cur else "РЕЖИМ: кастомный (микс настроек)")
                                mode_label.style("color:" + ("var(--ok)" if cur == "local" else
                                                 "var(--warn)" if cur == "cloud" else "var(--accent)") + ";")
                            except Exception:
                                pass
                            active = (providers.get("active") or "mlx").lower()
                            set_provider.set_value(active if active in ("mlx", "ollama", "openrouter", "openai") else "mlx")
                            ollama = providers.get("ollama") or {}
                            set_ollama_url.set_value(ollama.get("base_url", "http://127.0.0.1:11434"))
                            set_ollama_model.set_value(ollama.get("model", ""))
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
                            set_cloud_consent.set_value(bool(d.get("cloud_consent")))
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
                                "llm_provider": set_provider.value or "mlx",
                                "ollama_base_url": set_ollama_url.value or "",
                                "ollama_model": set_ollama_model.value or "",
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
                                "cloud_consent": bool(set_cloud_consent.value),
                            }
                            d = await api_post("/api/settings", payload)
                            if d:
                                add_log(f"[SETTINGS] Сохранено: провайдер={set_provider.value}, LLM={set_llm.value}")
                                ui.notify(f"Сохранено. Отвечает: {str(set_provider.value).upper()} — применяется сразу", type="positive")
                                await _load_settings()  # обновить строку «СЕЙЧАС ОТВЕЧАЕТ»
                                settings_dialog.close()
                            else:
                                ui.notify(last_api_error_text("Ошибка сохранения настроек"), type="negative")

                        ui.button("💾 Сохранить", on_click=save_settings).props("no-caps").style(
                            "border:1px solid var(--accent);color:var(--accent);background:transparent;"
                        )

                ui.button(icon="o_settings", on_click=lambda: settings_dialog.open()).props('flat dense round aria-label="Настройки"').style("color:var(--dim);")

            # Пользователь / выход
            ui.button(auth_holder or auth_role, icon=("o_shield" if is_admin else "o_person"),
                      on_click=lambda: (logout(), ui.navigate.to("/login"))
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
