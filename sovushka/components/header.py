"""
С.О.В.У.Ш.К.А. v5.0 — Шапка (Header) со встроенными табами
"""
from __future__ import annotations

import asyncio
import json
import sys
from nicegui import app, ui

from backend.auth import logout
from proxy.services.llm_transport_profile_service import freetoken_prompt_chars_for_context
from sovushka.components.charts import _html
from sovushka.state import api_get, last_api_error_text, proxy_online
from sovushka.styles import _DARK_THEME, _LIGHT_THEME
from sovushka.uikit.components import acronym_identity, action_button


def _smeta_runtime_settings(engine: str, model: str) -> dict[str, str]:
    """Native smeta follows the active LES runtime instead of a shadow route."""

    if str(engine or "native").strip().lower() == "native":
        return {
            "smeta_document_provider": "",
            "smeta_document_model": "",
        }
    return {
        "smeta_document_provider": "",
        "smeta_document_model": str(model or "").strip(),
    }


def visible_workspace_sections() -> tuple[str, ...]:
    """Product-visible workspace sections; legacy RIM remains data-compatible only."""
    return ("chat", "data", "history")


def build_header(
    is_admin: bool,
    auth_role: str,
    auth_holder: str,
    *,
    admin_tabs: bool | None = None,
    include_chat: bool = True,
    include_data: bool = False,
    admin_link: bool = False,
    chat_link: bool = False,
    active_primary: str = "",
    visualizer_url: str | None = None,
):
    """
    Строит единую sticky-полосу: [лого] [табы] [контролы].
    Возвращает (tabs, tab_objects_dict) — используется в sovushka_ng.py для tab_panels.
    """

    tab_refs = {}
    show_admin_tabs = is_admin if admin_tabs is None else admin_tabs
    is_windows = sys.platform.startswith("win")

    with ui.element("header").classes("w-full sov-ui-header").style(
        "position:sticky;top:0;z-index:999;"
        "background:var(--bg-panel);border-bottom:1px solid var(--border);"
        "display:flex;align-items:center;padding:0 16px;height:56px;gap:0;"
    ) as header_container:
        # ── Лого ──────────────────────────────────────────────────────────────
        with ui.row().classes("items-center sov-brand-block").style(
            "gap:6px;margin-right:12px;white-space:nowrap;flex-wrap:nowrap;"
        ):
            acronym_identity(
                "Л.Е.С.",
                "Локальная Единая Система",
                icon="o_forest",
                compact=True,
            )

        # ── Бейдж версии (v0.19): что реально запущено — версия+commit+runtime-divergence ──
        _ver_state: dict = {"info": None}
        ver_badge = ui.button("· · ·").props("flat dense no-caps").classes(
            "sov-ui-version-badge"
        ).style(
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

        async def _open_version_dialog() -> None:
            info = await api_get("/api/version")
            if isinstance(info, dict) and info:
                _ver_state["info"] = info
            else:
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

        ver_badge.on("click", _open_version_dialog)

        async def _load_version() -> None:
            info = await api_get("/api/version")
            if isinstance(info, dict):
                _ver_state["info"] = info
                # В шапке оставляем читаемую версию; commit и contract доступны
                # в диалоге по клику, а не съедают место основной навигации.
                product = info.get("product_version") or info.get("app_version", "?")
                build = info.get("build_number")
                ver_badge.set_text(f"{product}" + (f" · {build}" if build is not None else ""))
                al = (info.get("runtime_alignment") or {}).get("status")
                ds = (info.get("deploy_stamp") or {}).get("status")
                if al == "divergent" or ds in ("stale", "deploy_stamp_missing"):
                    ver_badge.style("color:var(--warn);border-color:var(--warn);")
            else:
                ver_badge.set_text("?")

        ui.timer(0.4, _load_version, once=True)

        # ── Первичные поверхности: одинаковы в чате, Студии и конфигурации ───
        if is_admin and (chat_link or admin_link):
            nav_buttons: dict[str, object] = {}

            def _open_primary(key: str, target: str) -> None:
                # Chat and Studio are panels of the same /classic page. A full
                # navigation rebuilt the 4k-line chat surface, repeated startup
                # probes and made a local tab switch take tens of seconds.
                if key in {"chat", "studio"} and key in tab_refs:
                    tabs.set_value(tab_refs[key])
                    ui.run_javascript(
                        f"window.history.replaceState(null, '', {json.dumps(target)})"
                    )
                    for button_key, button in nav_buttons.items():
                        if button_key == key:
                            button.classes(add="sov-nav-switch--active")
                            button.props('aria-current="page"')
                        else:
                            button.classes(remove="sov-nav-switch--active")
                            button.props(remove="aria-current")
                    return
                ui.navigate.to(target)

            def _primary_button(
                key: str,
                label: str,
                icon: str,
                target: str,
                tooltip: str,
            ):
                active = key == active_primary
                classes = (
                    f"sov-nav-switch sov-nav-switch--{key}"
                    + (" sov-nav-switch--active" if active else "")
                )
                button = ui.button(
                    label,
                    color=None,
                    icon=icon,
                    on_click=lambda key=key, target=target: _open_primary(key, target),
                ).props(
                    f'flat no-caps aria-label="{label}"'
                    + (' aria-current="page"' if active else "")
                ).classes(classes).tooltip(tooltip)
                nav_buttons[key] = button
                return button

            with ui.row().classes("sov-primary-nav sov-mobile-primary-nav"):
                _primary_button(
                    "chat",
                    "Чат",
                    "o_forum",
                    "/classic?tab=chat",
                    "Перейти в рабочий чат",
                )
                _primary_button(
                    "config",
                    "Конфигурация",
                    "o_tune",
                    "/les/classic",
                    "Открыть состояние и настройки ЛЕС",
                )
            tab_refs["_primary_nav"] = nav_buttons

        ui.label("Рабочие разделы").classes("sov-sidebar-caption")

        # ── Вторичные рабочие разделы ─────────────────────────────────────────
        with ui.tabs().classes("les-top-tabs").props("dense no-caps").style(
            "flex:1;min-width:0;background:transparent;border:none;"
            "font-family:var(--font);font-size:.65rem;font-weight:700;"
            "color:var(--dim);height:56px;"
        ) as tabs:
            if show_admin_tabs:
                # v0.24: админка с чистыми именами; рабочие инструменты оставляем видимыми,
                # иначе оператор не видит служебные источники, ВОР и нормоконтроль.
                tab_refs["diag"]       = ui.tab("Состояние", icon="o_health_and_safety")
                tab_refs["instrumenty"] = ui.tab("Инструменты", icon="o_build")
                tab_refs["model_connections"] = ui.tab("Модели", icon="o_hub")
                tab_refs["profiles"] = ui.tab("Профили", icon="o_manage_accounts")
                tab_refs["qdrant_viz"] = ui.tab("Визуал",    icon="o_scatter_plot")
                tab_refs["volk"]       = ui.tab("Доступ",    icon="o_vpn_key")  # В.О.Л.К. — контур доступа
            if include_chat:
                tab_refs["chat"] = ui.tab("AI ЧАТ", icon="o_forum").classes(
                    "sov-primary-tab-mirrored"
                )
                if include_data:
                    tab_refs["data"] = ui.tab("Данные", icon="o_database")
                tab_refs["history"]  = ui.tab("История",        icon="o_history")

        for key, label in {
            "diag": "Состояние",
            "data": "Данные",
            "history": "История",
            "instrumenty": "Инструменты",
            "model_connections": "Модели",
            "profiles": "Профили чата",
            "qdrant_viz": "Визуализация Qdrant",
            "volk": "Доступ",
        }.items():
            if key in tab_refs:
                tab_refs[key].tooltip(label)

        mobile_sections = (
            ("diag", "Состояние"),
            ("data", "Данные"),
            ("history", "История"),
            ("instrumenty", "Инструменты"),
            ("model_connections", "Модели"),
            ("profiles", "Профили"),
            ("qdrant_viz", "Визуал"),
            ("volk", "Доступ"),
        )
        with ui.button("Разделы", icon="o_apps").props(
            'flat dense no-caps aria-label="Рабочие разделы"'
        ).classes("sov-mobile-sections-button"):
            with ui.menu().classes("sov-mobile-sections-menu"):
                for key, label in mobile_sections:
                    if key in tab_refs:
                        ui.menu_item(
                            label,
                            on_click=lambda tab=tab_refs[key]: tabs.set_value(tab),
                        )

        # ── Служебная зона: статус и действия собраны в один ровный блок ─────
        with ui.column().classes("sov-ui-header-controls").style(
            "flex-shrink:0;margin-left:8px;"
        ) as utility_controls:

            # W5.3: индикатор доступности proxy (зелёный — на связи, красный — нет)
            with ui.row().classes("sov-runtime-state"):
                proxy_dot = ui.icon("circle").classes("sov-runtime-dot").style(
                    "font-size:.6rem;color:#10b981;"
                )
                proxy_label = ui.label("ЛЕС на связи").classes("sov-runtime-label")
            proxy_dot.tooltip("Связь с proxy")

            def _upd_proxy_dot():
                online = proxy_online()
                proxy_dot.style(
                    f"font-size:.6rem;color:{'#10b981' if online else '#ef4444'};"
                )
                proxy_label.set_text("ЛЕС на связи" if online else "Нет связи с ЛЕС")

            ui.timer(3.0, _upd_proxy_dot)

            # Обновить данные текущего экрана (не обновление приложения).
            ui.button("Обновить данные", icon="o_refresh", on_click=lambda: asyncio.create_task(_full_refresh())
            ).props('flat dense no-caps aria-label="Обновить данные"').classes(
                "sov-ui-header-utility"
            )

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
                "Тема",
                icon=("o_dark_mode" if _dark_init else "o_light_mode"),
                on_click=_toggle_theme,
            ).props('flat dense no-caps aria-label="Переключить тему"').classes(
                "sov-ui-header-utility"
            )

            if not _dark_init:
                ui.run_javascript("if(window.Quasar){Quasar.Dark.set(false);}")

            if is_admin:
                if visualizer_url:
                    with ui.link(
                        target=visualizer_url,
                        new_tab=True,
                    ).classes("no-underline sov-ui-header-secondary"):
                        ui.icon("o_scatter_plot")
                        ui.label("Qdrant")

                # Настройки
                with ui.dialog() as settings_dialog, ui.card().style(
                    "background:var(--bg-panel);border:1px solid var(--border);min-width:640px;padding:24px;"
                ):
                    acronym_identity(
                        "Л.Е.С.",
                        "Локальная Единая Система",
                        icon="o_forest",
                    )
                    ui.label("Настройки").style(
                        "font-size:.95rem;font-weight:800;margin:2px 0 8px;"
                    )
                    ui.label("Подключения моделей перенесены в Конфигурация → Модели.").classes(
                        "sov-ui-section-detail"
                    )

                    def _set_acronym_expansions(event) -> None:
                        visible = bool(event.value)
                        app.storage.user["show_acronym_expansions"] = visible
                        ui.run_javascript(
                            "document.body.classList.toggle("
                            "'sov-hide-acronym-expansions', "
                            f"{str(not visible).lower()})"
                        )

                    ui.switch(
                        "Показывать расшифровки акронимов",
                        value=bool(app.storage.user.get("show_acronym_expansions", True)),
                        on_change=_set_acronym_expansions,
                    ).props("dense color=positive").classes(
                        "sov-acronym-preference"
                    ).tooltip(
                        "Акронимы остаются; скрываются только поясняющие строки"
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
                    provider_options = {
                        "freetoken": "FreeToken — локально",
                        "ollama": "Ollama — локально",
                        "openrouter": "OpenRouter — облако",
                        "openai": "OpenAI-compatible — облако",
                    }
                    if not is_windows:
                        provider_options = {"mlx": "MLX — локально на Mac", **provider_options}
                    set_provider = ui.select(
                        provider_options,
                        label="Активный LLM-провайдер",
                        value="ollama" if is_windows else "mlx",
                    ).style("width:100%;font-family:var(--font);")
                    with ui.column().classes("w-full gap-2") as mlx_settings:
                        # Mac-only MLX runtime. Windows production uses Ollama and never shows these controls.
                        _mlx_loading = {"v": False}
                        set_llm = ui.select({}, label="Локальная модель MLX").props(
                            "dense outlined"
                        ).style("width:100%;font-family:var(--font);")
                        set_embed = ui.input("Модель эмбеддингов MLX", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                        set_url = ui.input("Адрес MLX", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    mlx_settings.set_visibility(not is_windows)

                    async def _apply_mlx_model(e) -> None:
                        if _mlx_loading["v"] or is_windows:
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
                    set_ollama_url = ui.input("Адрес Ollama", value="http://127.0.0.1:11434").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_ollama_model = ui.input("Модель Ollama, например gemma4:12b", value="").style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_freetoken_url = ui.input(
                        "Адрес FreeToken", value="http://127.0.0.1:1919/v1"
                    ).style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    set_freetoken_model = ui.input(
                        "Модель FreeToken", value=""
                    ).style("background:var(--bg);color:var(--text);font-family:var(--font);width:100%;")
                    with ui.row().classes("w-full gap-2"):
                        set_freetoken_context = ui.number(
                            "Контекст FreeToken, токены", value=8253, min=1024, step=1
                        ).style("background:var(--bg);color:var(--text);font-family:var(--font);flex:1;")
                        set_freetoken_prompt = ui.number(
                            "Лимит промта, символы",
                            value=freetoken_prompt_chars_for_context(8253),
                            min=1024,
                            step=1,
                        ).style("background:var(--bg);color:var(--text);font-family:var(--font);flex:1;")

                        def _sync_freetoken_prompt_budget(event) -> None:
                            try:
                                context_tokens = int(float(event.value or 8253))
                            except (TypeError, ValueError):
                                context_tokens = 8253
                            set_freetoken_prompt.set_value(
                                freetoken_prompt_chars_for_context(context_tokens)
                            )

                        set_freetoken_context.on_value_change(_sync_freetoken_prompt_budget)
                    freetoken_cache_label = ui.label(
                        "Физический KV: проверяется"
                    ).classes("text-caption").style("color:var(--dim);")
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
                    # W3.3/ADR-9: данные по чувствительности. P0 — только локально,
                    # P1 — можно в облако, P2 — облако ТОЛЬКО при этом согласии. Уровень
                    # датасета ставится в САМОВАРе (колонка «Данные»).
                    set_cloud_consent = ui.checkbox("Разрешить облако для данных P2 (согласие)", value=False).style(
                        "color:var(--warn);font-family:var(--font);font-weight:700;"
                    )
                    _html(
                        '<div class="sov-muted" style="font-size:.6rem;line-height:1.4;">P0 (приватные: НТД по умолчанию, '
                        'почта, договоры) всегда остаются на этой машине. Уровень датасета — в САМОВАРе → «Данные».</div>'
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
                            "freetoken": (providers.get("freetoken") or {}).get("model") or llm_fallback,
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
                            default_provider = "ollama" if is_windows else "mlx"
                            set_provider.set_value(active if active in provider_options else default_provider)
                            ollama = providers.get("ollama") or {}
                            set_ollama_url.set_value(ollama.get("base_url", "http://127.0.0.1:11434"))
                            set_ollama_model.set_value(ollama.get("model", ""))
                            freetoken = providers.get("freetoken") or {}
                            set_freetoken_url.set_value(
                                freetoken.get("base_url", "http://127.0.0.1:1919/v1")
                            )
                            set_freetoken_model.set_value(freetoken.get("model", ""))
                            set_freetoken_context.set_value(freetoken.get("context_tokens", 8253))
                            set_freetoken_prompt.set_value(
                                freetoken.get(
                                    "prompt_max_chars",
                                    freetoken_prompt_chars_for_context(
                                        int(freetoken.get("context_tokens", 8253) or 8253)
                                    ),
                                )
                            )
                            cache = freetoken.get("cache") or {}
                            effective_kv = cache.get("effective_kv_tokens")
                            desired_kv = cache.get("desired_kv_tokens")
                            cache_status = str(cache.get("status") or "unknown")
                            if effective_kv:
                                freetoken_cache_label.set_text(
                                    f"Физический KV: {effective_kv} / {desired_kv} · {cache_status}"
                                )
                            else:
                                freetoken_cache_label.set_text(
                                    f"Физический KV: недоступен · {cache_status}"
                                )
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
                    update_check_path = (
                        "/api/update/patch/check" if is_windows else "/api/update/mac/check"
                    )
                    update_install_path = (
                        "/api/update/patch/install" if is_windows else "/api/update/mac/install"
                    )
                    update_status_path = (
                        "/api/update/patch/status" if is_windows else "/api/update/mac/status"
                    )
                    def _set_patch_update_status(text: str) -> None:
                        update_status.set_text(text)

                    def _set_patch_install_enabled(enabled: bool) -> None:
                        if enabled:
                            update_button.enable()
                        else:
                            update_button.disable()

                    async def _check_application_update() -> None:
                        from sovushka.state import api_get

                        _set_patch_install_enabled(False)
                        _set_patch_update_status("Проверяю подготовленный пакет…")
                        result = await api_get(update_check_path)
                        if not isinstance(result, dict):
                            _set_patch_update_status(last_api_error_text("Не удалось проверить обновление"))
                            return
                        if not result.get("available"):
                            _set_patch_update_status(str(result.get("message") or "Обновлений нет."))
                            return
                        if not result.get("compatible"):
                            _set_patch_update_status(str(result.get("message") or "Требуется полный выпуск."))
                            return
                        package_kib = max(1, int(result.get("bytes") or 0) // 1024)
                        _set_patch_update_status(
                            f"Готово: {int(result.get('files') or 0)} файлов · {package_kib} КБ · "
                            "с автоматическим откатом."
                        )
                        _set_patch_install_enabled(True)

                    async def _install_application_update() -> None:
                        from sovushka.state import api_post

                        _set_patch_install_enabled(False)
                        _set_patch_update_status("Проверяю пакет и точку отката…")
                        result = await api_post(update_install_path, {})
                        if not isinstance(result, dict):
                            _set_patch_update_status(last_api_error_text("Не удалось запустить обновление"))
                            return
                        _set_patch_update_status("Пакет проверен. ЛЕС перезапустится и проверит версию и health.")
                        ui.notify("Быстрое обновление запущено", type="positive")

                        async def _watch_patch() -> None:
                            for _ in range(120):
                                await asyncio.sleep(2)
                                state = await api_get(update_status_path)
                                if not isinstance(state, dict):
                                    continue
                                _set_patch_update_status(str(state.get("message") or "Обновляю ЛЕС…"))
                                if state.get("state") in {"ready", "failed"}:
                                    if state.get("state") == "ready":
                                        ui.notify("ЛЕС обновлён", type="positive")
                                    else:
                                        ui.notify("Обновление отменено, предыдущая версия восстановлена", type="negative")
                                    return

                        asyncio.create_task(_watch_patch())

                    if is_windows:
                        async def _check_hard_update() -> None:
                            from sovushka.state import api_get

                            hard_update_button.disable()
                            hard_update_status.set_text("Проверяю полный выпуск и его SHA-256…")
                            result = await api_get("/api/update/check")
                            if not isinstance(result, dict):
                                hard_update_status.set_text(
                                    last_api_error_text("Не удалось проверить полный выпуск")
                                )
                                return
                            if not result.get("available"):
                                hard_update_status.set_text("Нового полного выпуска нет.")
                                return
                            if not result.get("package_complete"):
                                hard_update_status.set_text(
                                    "Выпуск неполный: нет commit, build или версии оболочки."
                                )
                                return
                            hard_update_status.set_text(
                                f"Готов выпуск {result.get('latest_version')} · "
                                f"build {result.get('build_number')} · с автоматическим откатом."
                            )
                            hard_update_button.enable()

                        async def _install_hard_update() -> None:
                            from sovushka.state import api_get, api_post

                            hard_update_button.disable()
                            hard_update_status.set_text("Скачиваю и проверяю полный installer…")
                            result = await api_post("/api/update/install", {})
                            if not isinstance(result, dict):
                                hard_update_status.set_text(
                                    last_api_error_text("Не удалось запустить переустановку")
                                )
                                return
                            hard_update_status.set_text(
                                "Installer проверен. Приложение будет заменено одной транзакцией."
                            )

                            async def _watch_hard_update() -> None:
                                for _ in range(150):
                                    await asyncio.sleep(2)
                                    state = await api_get("/api/update/status")
                                    if not isinstance(state, dict):
                                        continue
                                    hard_update_status.set_text(
                                        str(state.get("message") or "Переустанавливаю ЛЕС…")
                                    )
                                    if state.get("state") in {"ready", "failed"}:
                                        return

                            asyncio.create_task(_watch_hard_update())

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
                                "llm_provider": set_provider.value or ("ollama" if is_windows else "mlx"),
                                "ollama_base_url": set_ollama_url.value or "",
                                "ollama_model": set_ollama_model.value or "",
                                "freetoken_base_url": set_freetoken_url.value or "",
                                "freetoken_model": set_freetoken_model.value or "",
                                "freetoken_context_tokens": int(set_freetoken_context.value or 8253),
                                "freetoken_prompt_max_chars": int(
                                    set_freetoken_prompt.value
                                    or freetoken_prompt_chars_for_context(
                                        int(set_freetoken_context.value or 8253)
                                    )
                                ),
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

                with ui.dialog() as update_dialog, ui.card().classes("sov-ui-dialog-card"):
                    ui.label("Обновление ЛЕС").classes("sov-ui-section-title")
                    update_status = ui.label(
                        "Устанавливается только заранее подготовленный пакет кода. "
                        "Тесты и сборка по кнопке не запускаются; рабочие данные не затрагиваются."
                    ).classes("sov-ui-section-detail")
                    with ui.row().classes("w-full gap-2"):
                        ui.button(
                            "Проверить обновление",
                            icon="o_system_update_alt",
                            on_click=_check_application_update,
                        ).props("no-caps flat")
                        update_button = ui.button(
                            "Установить",
                            icon="o_download",
                            on_click=_install_application_update,
                        ).props("no-caps disable")
                        ui.button("Закрыть", on_click=update_dialog.close).props("no-caps flat")

                    if is_windows:
                        ui.separator().style("border-color:var(--border);margin:8px 0;")
                        hard_update_status = ui.label(
                            "Полный выпуск нужен только для оболочки, установщика или встроенного runtime. "
                            "Пользовательские данные сохраняются."
                        ).classes("sov-ui-section-detail")
                        with ui.row().classes("w-full gap-2"):
                            ui.button(
                                "Проверить полный выпуск",
                                icon="o_verified",
                                on_click=_check_hard_update,
                            ).props("no-caps flat")
                            hard_update_button = ui.button(
                                "Переустановить выпуск",
                                icon="o_system_update",
                                on_click=_install_hard_update,
                            ).props("no-caps disable")

                update_entry_button = ui.button(
                    "Обновить ЛЕС",
                    icon="o_system_update_alt",
                    on_click=update_dialog.open,
                ).props('flat dense no-caps aria-label="Обновить ЛЕС"').classes(
                    "sov-ui-header-utility"
                )

                async def _check_update_in_background() -> None:
                    from sovushka.state import api_get

                    result = await api_get(update_check_path)
                    if not isinstance(result, dict):
                        return
                    if result.get("available") and result.get("compatible"):
                        update_entry_button.set_text("Доступно обновление")
                        update_entry_button.style(
                            "border-color:var(--warn);color:var(--warn);font-weight:900;"
                        )
                        _set_patch_update_status(str(result.get("message") or "Доступен патч ЛЕС."))
                        _set_patch_install_enabled(True)

                ui.timer(5.0, _check_update_in_background, once=True)
                ui.timer(86400.0, _check_update_in_background)
                ui.button("Настройки", icon="o_settings", on_click=lambda: ui.navigate.to("/les/classic?tab=models")).props(
                    'flat dense no-caps aria-label="Настройки"'
                ).classes("sov-ui-header-action").style("color:var(--dim);font-size:.62rem;")

            # Пользователь / выход
            account_detail = auth_holder or auth_role
            ui.button(
                "Профиль",
                icon=("o_shield" if is_admin else "o_person"),
                on_click=lambda: (logout(), ui.navigate.to("/login")),
            ).props("flat no-caps dense").classes(
                "sov-ui-header-action sov-ui-header-account"
            ).tooltip(f"Сеанс: {account_detail}. Нажмите, чтобы выйти")

    if active_primary == "chat":
        with header_container:
            with action_button("Приложение", icon="o_more_horiz", variant="quiet",
                               classes="sov-chat-application-menu-button"):
                with ui.menu().classes("sov-chat-utility-menu") as utility_menu:
                    utility_controls.move(utility_menu)

    return tabs, tab_refs


# ── Приватные функции ─────────────────────────────────────────────────────────

async def _full_refresh():
    from sovushka.state import refresh_metrics, refresh_status, refresh_mlx, refresh_samovar, add_log
    add_log("[REFRESH] Полное обновление...")
    await asyncio.gather(refresh_metrics(), refresh_status(), refresh_mlx(), refresh_samovar())
    add_log("[REFRESH] Готово.")
