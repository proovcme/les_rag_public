"""V.O.L.K. access-management surface."""

from __future__ import annotations

import secrets
from typing import Any

from nicegui import app, ui

from sovushka.state import api_get, api_post, last_api_error_text
from sovushka.uikit.components import (
    acronym_identity,
    action_button,
    panel,
    render_feedback_state,
    section_heading,
    select_field,
    status_badge,
    text_field,
)


def build_volk():
    """Render access keys as readable operator rows instead of a technical grid."""

    raw_key = str(app.storage.user.get("key", ""))
    state: dict[str, Any] = {"loading": True, "error": "", "rows": []}
    refs: dict[str, Any] = {}

    def key_preview(value: str) -> str:
        if len(value) <= 14:
            return value
        return f"{value[:8]}…{value[-4:]}"

    def render_keys() -> None:
        container = refs.get("keys")
        if container is None:
            return
        container.clear()
        with container:
            if state["loading"]:
                render_feedback_state("loading", detail="Читаю ключи доступа.")
                return
            if state["error"]:
                render_feedback_state("error", detail=state["error"])
                return
            if not state["rows"]:
                render_feedback_state(
                    "empty",
                    detail="Дополнительных ключей пока нет. Создайте первый ключ выше.",
                )
                return
            for row in state["rows"]:
                protected = bool(row.get("protected_admin"))
                active = bool(row.get("is_active"))
                holder = str(row.get("holder_name") or "Без имени")
                role = str(row.get("role") or "user")
                expires = str(row.get("expires_at") or "")
                created = str(row.get("created_at") or "")[:10]
                device_bound = bool(row.get("device_bound"))
                with panel(variant="plain", classes="sov-access-key-row"):
                    with ui.row().classes("sov-access-key-row__main"):
                        ui.icon("o_admin_panel_settings" if role == "admin" else "o_key").classes(
                            "sov-access-key-row__icon"
                        )
                        with ui.column().classes("sov-access-key-row__copy"):
                            with ui.row().classes("sov-access-key-row__identity"):
                                ui.label(holder).classes("sov-access-key-row__holder")
                                status_badge("root" if protected else role, "ok" if active else "muted")
                                status_badge("активен" if active else "выключен", "ok" if active else "warn")
                            ui.label(
                                "Системный ключ без привязки"
                                if protected
                                else key_preview(str(row.get("key_value") or ""))
                            ).classes("sov-access-key-row__key")
                            with ui.row().classes("sov-access-key-row__meta"):
                                ui.label(f"создан {created or '—'}")
                                ui.label(f"истекает {expires[:10] if expires else 'никогда'}")
                                ui.label("устройство привязано" if device_bound else "без устройства")
                    if protected:
                        ui.label("Защищён").classes("sov-access-key-row__protected")
                    else:
                        with ui.row().classes("sov-access-key-row__actions"):
                            action_button(
                                "Выключить" if active else "Включить",
                                icon="o_toggle_off" if active else "o_toggle_on",
                                on_click=lambda _event, item=row: toggle_key(item),
                                variant="secondary",
                                compact=True,
                            )
                            if device_bound:
                                action_button(
                                    "Отвязать",
                                    icon="o_phonelink_erase",
                                    on_click=lambda _event, item=row: reset_device(item),
                                    variant="quiet",
                                    compact=True,
                                )
                            action_button(
                                "Удалить",
                                icon="o_delete_outline",
                                on_click=lambda _event, item=row: delete_key(item),
                                variant="danger",
                                compact=True,
                            )

    async def load_keys() -> None:
        state["loading"] = True
        state["error"] = ""
        render_keys()
        rows = await api_get("/api/auth/keys")
        if rows is None:
            state["rows"] = []
            state["error"] = "Ключи сейчас недоступны. Проверьте соединение с ЛЕС и повторите."
        else:
            state["rows"] = rows if isinstance(rows, list) else []
        state["loading"] = False
        render_keys()

    async def create_key() -> None:
        value = str(refs["key"].value or "").strip()
        holder = str(refs["holder"].value or "").strip()
        role = str(refs["role"].value or "user")
        duration = str(refs["duration"].value or "permanent")
        if not value:
            ui.notify("Введите или сгенерируйте ключ", type="warning")
            return
        expires_days = 0 if duration == "permanent" else int(duration)
        result = await api_post(
            "/api/auth/keys",
            {
                "key_value": value,
                "holder_name": holder,
                "role": role,
                "expires_days": expires_days,
            },
        )
        if not result:
            ui.notify(last_api_error_text("Ошибка создания ключа"), type="negative")
            return
        refs["key"].set_value("")
        refs["holder"].set_value("")
        ui.notify("Ключ создан", type="positive")
        await load_keys()

    def generate_key() -> None:
        role = str(refs["role"].value or "user")
        prefix = "les-admin-" if role == "admin" else "les_"
        refs["key"].set_value(prefix + secrets.token_hex(12 if role == "admin" else 8))

    async def toggle_key(row: dict[str, Any]) -> None:
        value = str(row.get("key_value") or "")
        active = bool(row.get("is_active"))
        result = await api_post(
            "/api/auth/keys/toggle",
            {"key_value": value, "is_active": 0 if active else 1},
        )
        if result:
            await load_keys()
        else:
            ui.notify(last_api_error_text("Ошибка переключения ключа"), type="negative")

    async def reset_device(row: dict[str, Any]) -> None:
        value = str(row.get("key_value") or "")
        result = await api_post(
            "/api/auth/keys/reset-device",
            {"key_value": value, "is_active": 1},
        )
        if result:
            ui.notify("Устройство отвязано", type="positive")
            await load_keys()
        else:
            ui.notify(last_api_error_text("Ошибка отвязки устройства"), type="negative")

    async def delete_key(row: dict[str, Any]) -> None:
        value = str(row.get("key_value") or "")
        if value == raw_key:
            ui.notify("Нельзя удалить свой ключ", type="warning")
            return
        result = await api_post("/api/auth/keys/delete", {"key_value": value})
        if result:
            ui.notify("Ключ удалён", type="warning")
            await load_keys()
        else:
            ui.notify(last_api_error_text("Ошибка удаления ключа"), type="negative")

    with ui.column().classes("sov-access-page"):
        with panel(variant="raised", classes="sov-access-hero"):
            with ui.row().classes("sov-access-hero__row"):
                with ui.column().classes("sov-access-hero__copy"):
                    acronym_identity(
                        "В.О.Л.К.",
                        "Внутренний Охранный Локальный Контур",
                        icon="o_vpn_key",
                    )
                    ui.label(
                        "Выдавайте минимально необходимый доступ и сразу видьте активность, срок и привязку."
                    ).classes("sov-access-intro")
                action_button(
                    "Обновить",
                    icon="o_refresh",
                    on_click=load_keys,
                    variant="secondary",
                )
        with panel(variant="plain", classes="sov-access-create"):
            section_heading(
                "Новый ключ",
                "Секрет показывается только в форме создания; в реестре остаётся короткий безопасный preview.",
            )
            with ui.element("section").classes("sov-access-form"):
                refs["key"] = text_field(
                    label="Ключ",
                    placeholder="Введите или сгенерируйте",
                    classes="sov-access-form__key",
                )
                refs["holder"] = text_field(
                    label="Кому",
                    placeholder="Имя пользователя",
                    classes="sov-access-form__holder",
                )
                refs["role"] = select_field(
                    {"user": "Пользователь", "admin": "Администратор"},
                    value="user",
                    label="Роль",
                    classes="sov-access-form__role",
                )
                refs["duration"] = select_field(
                    {"permanent": "Без срока", "1": "1 день"},
                    value="permanent",
                    label="Срок",
                    classes="sov-access-form__duration",
                )
            with ui.row().classes("sov-access-form__actions"):
                action_button(
                    "Сгенерировать",
                    icon="o_casino",
                    on_click=generate_key,
                    variant="quiet",
                )
                action_button(
                    "Создать ключ",
                    icon="o_add",
                    on_click=create_key,
                    variant="primary",
                )
        with panel(variant="plain", classes="sov-access-registry"):
            with ui.row().classes("sov-access-registry__head"):
                section_heading(
                    "Ключи доступа",
                    "Root-ключ защищён; остальные можно выключить, отвязать или удалить.",
                )
                status_badge("локальный контур", "muted")
            refs["keys"] = ui.column().classes("sov-access-key-list")

    ui.timer(0.1, load_keys, once=True)
