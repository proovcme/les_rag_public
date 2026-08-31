"""GUI-first administrator registry for provider-neutral model connections."""
from __future__ import annotations

import asyncio
from typing import Any

from nicegui import ui

from sovushka.state import api_get, api_post, api_put, last_api_error_text
from sovushka.uikit import action_button, panel, section_heading, select_field, status_badge, text_field
from sovushka.uikit.components import render_feedback_state


_LOCALITY = {
    "loopback": "На этом компьютере",
    "private_network": "В доверенной сети",
    "remote": "Удалённое HTTPS-подключение",
}
_ROLES = {"answer": "Ответы", "embeddings": "Эмбеддинги", "local_fallback": "Локальный резерв"}
_CAPS = {"models": "Список моделей", "chat_completions": "Чат", "streaming": "Поток", "embeddings": "Эмбеддинги", "tools": "Инструменты клиента", "responses": "Responses API"}


def suggested_connection_name(base_name: str, connections: list[dict[str, Any]]) -> str:
    base = str(base_name or "").strip() or "Подключение"
    occupied = {
        str(item.get("display_name") or "").strip().casefold()
        for item in connections
    }
    if base.casefold() not in occupied:
        return base
    suffix = 2
    while f"{base} {suffix}".casefold() in occupied:
        suffix += 1
    return f"{base} {suffix}"


def connection_save_error(raw_error: str) -> str:
    if "DISPLAY_NAME_IN_USE" in str(raw_error or ""):
        return "Такое название уже используется. Укажите другое название подключения."
    return str(raw_error or "Не удалось сохранить подключение")


def build_model_connections():
    data: dict[str, Any] = {
        "connections": [], "bindings": {}, "templates": [], "effective": {}, "qdrant": {},
    }
    refs: dict[str, Any] = {}

    async def _reload() -> None:
        refs["body"].clear()
        with refs["body"]:
            render_feedback_state("loading", detail="Читаю реестр подключений…")
        listing, templates, effective, runtime_registry = await asyncio.gather(
            api_get("/api/model-connections"),
            api_get("/api/model-connections/templates"),
            api_get("/api/model-connections/effective"),
            api_get("/api/settings/runtime-registry"),
        )
        if not isinstance(listing, dict):
            refs["body"].clear()
            with refs["body"]:
                render_feedback_state("error", detail=last_api_error_text("Реестр моделей недоступен"))
            return
        data["connections"] = list(listing.get("connections") or [])
        data["bindings"] = dict(listing.get("bindings") or {})
        data["templates"] = list((templates or {}).get("templates") or []) if isinstance(templates, dict) else []
        data["effective"] = dict((effective or {}).get("roles") or {}) if isinstance(effective, dict) else {}
        factors = list((runtime_registry or {}).get("factors") or []) if isinstance(runtime_registry, dict) else []
        data["qdrant"] = next((item for item in factors if item.get("key") == "QDRANT_URL"), {})
        _render()

    async def _save_qdrant(value: str) -> None:
        result = await api_put(
            "/api/settings/runtime-registry",
            {"updates": {"QDRANT_URL": value}, "danger_confirmations": []},
        )
        if result:
            ui.notify("Адрес Qdrant сохранён", type="positive")
            await _reload()
        else:
            ui.notify(last_api_error_text("Адрес Qdrant не сохранён"), type="negative")

    async def _bind(role: str, connection: dict[str, Any]) -> None:
        previous = data["bindings"].get(role) or {}
        result = await api_put(f"/api/model-connections/roles/{role}", {
            "connection_revision_id": connection["revision_id"],
            "expected_binding_revision": previous.get("binding_revision"),
        })
        if result:
            ui.notify(f"{_ROLES[role]}: назначено {connection['display_name']}", type="positive")
            await _reload()
        else:
            ui.notify(last_api_error_text("Не удалось назначить подключение"), type="negative")

    async def _test(connection: dict[str, Any]) -> None:
        result = await api_post(f"/api/model-connections/{connection['connection_id']}/test", {
            "revision_id": connection["revision_id"],
            "capabilities": ["models", "chat_completions", "streaming", "embeddings", "tools", "responses"],
        })
        ui.notify("Проверка завершена" if result else last_api_error_text("Проверка не выполнена"), type="positive" if result else "negative")
        await _reload()

    async def _disable(connection: dict[str, Any]) -> None:
        bound = [role for role, binding in data["bindings"].items() if binding and binding.get("connection_revision_id") == connection["revision_id"]]
        detail = ", ".join(_ROLES.get(role, role) for role in bound)
        ok = await ui.run_javascript(
            "confirm(" + repr(f"Отключить {connection['display_name']} ({connection['base_url']})?" + (f" Назначено: {detail}. BOUND_CONNECTION будет подтверждено." if bound else "")) + ")"
        )
        if not ok:
            return
        result = await api_post(f"/api/model-connections/{connection['connection_id']}/disable", {
            "expected_revision_id": connection["revision_id"], "confirm_bound_roles": bool(bound),
        })
        if result:
            ui.notify("Подключение отключено", type="positive")
            await _reload()
        else:
            ui.notify(last_api_error_text("Не удалось отключить подключение"), type="negative")

    def _open_editor(connection: dict[str, Any] | None = None, *, copy: bool = False) -> None:
        current = dict(connection or {})
        editing = bool(connection and not copy)
        selected_extension = {"value": current.get("extension_type")}
        with ui.dialog() as dialog, ui.card().classes("sov-model-dialog"):
            section_heading("Изменить подключение" if editing else "Новое подключение", "Секрет вводится вслепую и не возвращается из Л.Е.С.")
            template_options = {item["template_id"]: item["display_name"] for item in data["templates"]}
            template = select_field(template_options, label="Шаблон", clearable=True, classes="w-full")
            initial_name = current.get("display_name", "")
            if copy:
                initial_name = suggested_connection_name(
                    f"{initial_name} — копия",
                    data["connections"],
                )
            name = text_field(label="Название", value=initial_name, classes="w-full")
            endpoint = text_field(label="OpenAI-compatible URL", value=current.get("base_url", ""), classes="w-full")
            model = text_field(label="Модель", value=current.get("model_id", ""), classes="w-full")
            locality = select_field(_LOCALITY, value=current.get("locality", "loopback"), label="Расположение", classes="w-full")
            context = ui.number("Контекст, токены", value=current.get("requested_context_tokens"), min=1).props("outlined").classes("sov-ui-input w-full")
            secret_value = text_field(label="Новый ключ", placeholder="Оставьте пустым, если ключ не нужен", classes="w-full").props('type="password"')

            def _template_changed(event) -> None:
                row = next((x for x in data["templates"] if x.get("template_id") == event.value), None)
                if row:
                    selected_extension["value"] = row.get("extension_type")
                    name.set_value(
                        suggested_connection_name(
                            row.get("display_name", ""),
                            data["connections"],
                        )
                    ); endpoint.set_value(row.get("base_url", "")); locality.set_value(row.get("locality", "loopback"))
            template.on_value_change(_template_changed)

            async def _save() -> None:
                payload = {"display_name": name.value or "", "base_url": endpoint.value or "", "model_id": model.value or "", "locality": locality.value or "loopback", "requested_context_tokens": int(context.value) if context.value else None, "extension_type": selected_extension["value"]}
                if locality.value != "loopback":
                    ok = await ui.run_javascript("confirm(" + repr(f"Сохранить {_LOCALITY.get(locality.value, locality.value)}: {endpoint.value}?") + ")")
                    if not ok: return
                if editing:
                    payload["expected_revision_id"] = current["revision_id"]
                    result = await api_post(f"/api/model-connections/{current['connection_id']}/revisions", payload)
                else:
                    payload["secret_value"] = secret_value.value or None
                    result = await api_post("/api/model-connections", payload)
                if result:
                    dialog.close(); ui.notify("Подключение сохранено", type="positive"); await _reload()
                else:
                    raw_error = last_api_error_text("Не удалось сохранить подключение")
                    if "DISPLAY_NAME_IN_USE" in raw_error:
                        name.run_method("focus")
                    ui.notify(connection_save_error(raw_error), type="negative")
            with ui.row().classes("justify-end w-full"):
                action_button("Отмена", on_click=dialog.close, variant="quiet")
                action_button("Сохранить", on_click=_save, variant="primary")
        dialog.open()

    def _replace_secret(connection: dict[str, Any]) -> None:
        with ui.dialog() as dialog, ui.card().classes("sov-model-dialog"):
            section_heading("Заменить ключ", connection["display_name"])
            secret_value = text_field(label="Новый ключ", classes="w-full").props('type="password"')
            async def _save() -> None:
                result = await api_post(f"/api/model-connections/{connection['connection_id']}/secret", {"expected_revision_id": connection["revision_id"], "secret_value": secret_value.value or ""})
                if result: dialog.close(); await _reload()
                else: ui.notify(last_api_error_text("Ключ не заменён"), type="negative")
            action_button("Заменить", on_click=_save, variant="primary")
        dialog.open()

    def _render() -> None:
        body = refs["body"]; body.clear()
        with body:
            qdrant = data.get("qdrant") or {}
            with panel(variant="raised", classes="sov-model-summary"):
                section_heading(
                    "Подключение RAG",
                    "Qdrant хранит индекс. Ответы, эмбеддинги и резерв назначаются ниже независимо.",
                )
                with ui.row().classes("w-full items-end gap-2"):
                    qdrant_url = text_field(
                        label="Адрес Qdrant",
                        value=str(qdrant.get("display_value") or "http://127.0.0.1:6333"),
                        classes="grow",
                    )
                    action_button(
                        "Сохранить Qdrant",
                        icon="o_save",
                        on_click=lambda: asyncio.create_task(_save_qdrant(str(qdrant_url.value or ""))),
                        variant="secondary",
                    )
                ui.label(
                    f"Источник: {qdrant.get('source', 'default')} · применяется после перезапуска ЛЕС"
                ).classes("sov-ui-section-detail")
            with panel(variant="raised", classes="sov-model-summary"):
                section_heading("Роли модели", "Назначения атомарно привязаны к точной ревизии подключения.")
                with ui.row().classes("sov-model-role-grid"):
                    for role, label in _ROLES.items():
                        effective = data["effective"].get(role) or {}
                        with panel(variant="inset", classes="sov-model-role"):
                            ui.label(label).classes("sov-ui-section-title")
                            ui.label(effective.get("display_name") or "Не назначено")
                            if effective:
                                if role == "answer" and effective.get("status") != "blocked":
                                    status_badge("Работает в чате", "ok")
                                ui.label(f"Действует: {effective.get('input_token_limit', '—')} токенов · Источник: {effective.get('preset_id', '—')}").classes("sov-ui-section-detail")
            connections = data["connections"]
            if not connections:
                render_feedback_state("empty", detail="Создайте первое подключение модели.")
            for connection in connections:
                enabled = bool(connection.get("enabled")); caps = connection.get("capabilities") or []
                with panel(variant="plain", classes="sov-model-connection"):
                    with ui.row().classes("sov-model-connection__head"):
                        with ui.column().classes("grow gap-0"):
                            ui.label(connection.get("display_name") or "Без названия").classes("sov-ui-section-title")
                            ui.label(f"{connection.get('model_id')} · {_LOCALITY.get(connection.get('locality'), connection.get('locality'))}").classes("sov-ui-section-detail")
                        status_badge("Включено" if enabled else "Отключено", "ok" if enabled else "blocked")
                        status_badge("Ключ задан" if connection.get("secret_status") == "configured" else "Ключ не требуется" if connection.get("secret_status") == "not_required" else "Ключ не задан", "ok" if connection.get("secret_status") in {"configured", "not_required"} else "warn")
                    ui.label(connection.get("base_url") or "").classes("sov-ui-source-chip")
                    requested = connection.get("requested_context_tokens") or "автоматически"
                    ui.label(f"Запрошено: {requested} · Действует: после назначения · Источник: capability/preset · Перезапуск не требуется").classes("sov-ui-section-detail")
                    ui.label("Состояние проверки: " + ("; ".join(f"{_CAPS.get(x.get('name'), x.get('name'))}: {x.get('state')} · {x.get('observed_at')}" for x in caps) if caps else "ещё не проверялось")).classes("sov-ui-section-detail")
                    with ui.row().classes("sov-model-actions"):
                        action_button("Проверить", icon="o_fact_check", on_click=lambda _e, c=connection: _test(c), compact=True)
                        for role, role_label in _ROLES.items():
                            action_button(f"Назначить · {role_label}", on_click=lambda _e, r=role, c=connection: _bind(r, c), variant="quiet", compact=True)
                        action_button("Изменить", on_click=lambda _e, c=connection: _open_editor(c), variant="quiet", compact=True)
                        action_button("Копировать", on_click=lambda _e, c=connection: _open_editor(c, copy=True), variant="quiet", compact=True)
                        action_button("Заменить ключ", on_click=lambda _e, c=connection: _replace_secret(c), variant="quiet", compact=True)
                        if enabled: action_button("Отключить", on_click=lambda _e, c=connection: _disable(c), variant="danger", compact=True)

    with ui.column().classes("sov-model-connections-page"):
        with ui.row().classes("sov-model-page-head"):
            section_heading("Подключения моделей", "Единый OpenAI-compatible реестр для ответов, эмбеддингов и локального резерва.")
            action_button("Добавить подключение", icon="o_add", on_click=lambda: _open_editor(), variant="primary")
        with ui.column().classes("sov-model-connections-body") as body:
            refs["body"] = body
            render_feedback_state("loading", detail="Читаю реестр подключений…")
    ui.timer(0.1, _reload, once=True)
