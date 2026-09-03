"""Conversation history surface for Sovushka."""

from __future__ import annotations

import asyncio
from typing import Any

from nicegui import ui

from sovushka.pages.chat import format_chat_request_clock
from sovushka.state import add_log, api_get
from sovushka.uikit.components import (
    action_button,
    panel,
    render_feedback_state,
    section_heading,
    status_badge,
)


def build_history(tabs=None, tab_chat=None):
    """Render saved conversations and restore one into the active chat."""

    state: dict[str, Any] = {"loading": True, "error": "", "sessions": []}
    refs: dict[str, Any] = {}

    async def open_session(session_id: str) -> None:
        add_log(f"[ИСТОРИЯ] Загружаю сессию {session_id[:8]}…")
        messages = await api_get(f"/api/chat/history?session_id={session_id}")
        if messages is None:
            add_log("[ИСТОРИЯ] Ошибка загрузки сессии")
            ui.notify("Не удалось открыть диалог", type="negative")
            return
        from sovushka.state import state as app_state

        app_state["chat_history"] = messages
        app_state["load_session_id"] = session_id
        add_log(f"[ИСТОРИЯ] Загружено {len(messages) // 2} сообщений")
        if tabs and tab_chat:
            tabs.set_value(tab_chat)
        reload_hook = app_state.get("chat_reload_hook")
        if callable(reload_hook):
            try:
                reload_hook()
            except Exception as error:
                add_log(f"[ИСТОРИЯ] Хук перерисовки чата: {error}")

    def render_sessions() -> None:
        container = refs.get("sessions")
        if container is None:
            return
        container.clear()
        with container:
            if state["loading"]:
                render_feedback_state("loading", detail="Читаю сохранённые диалоги.")
                return
            if state["error"]:
                render_feedback_state("error", detail=state["error"])
                return
            sessions = state["sessions"]
            if not sessions:
                render_feedback_state(
                    "empty",
                    detail="Сохранённых диалогов пока нет. Новый разговор появится здесь автоматически.",
                )
                return
            for session in sessions:
                session_id = str(session.get("session_id") or "")
                first_question = str(session.get("first_question") or "Диалог без заголовка")
                message_count = int(session.get("msg_count") or 0)
                in_progress = bool(session.get("in_progress"))
                clock = format_chat_request_clock(
                    session.get("last_at") or session.get("started_at")
                ) or "Дата не указана"
                with panel(variant="plain", classes="sov-history-row"):
                    with ui.column().classes("sov-history-row__copy"):
                        ui.label(first_question).classes("sov-history-row__title")
                        with ui.row().classes("sov-history-row__meta"):
                            ui.label(clock)
                            ui.label("выполняется" if in_progress else f"{message_count} сообщ.")
                    action_button(
                        "Открыть",
                        icon="o_arrow_forward",
                        on_click=lambda _event, value=session_id: open_session(value),
                        variant="secondary",
                        classes="sov-history-row__open",
                    )

    async def load_sessions() -> None:
        state["loading"] = True
        state["error"] = ""
        render_sessions()
        payload = await api_get("/api/chat/sessions?limit=50")
        if payload is None:
            state["sessions"] = []
            state["error"] = "История сейчас недоступна. Проверьте соединение с ЛЕС и повторите."
        else:
            state["sessions"] = payload if isinstance(payload, list) else []
        state["loading"] = False
        render_sessions()

    with ui.column().classes("sov-history-page"):
        with panel(variant="raised", classes="sov-history-hero"):
            with ui.row().classes("sov-history-hero__row"):
                section_heading(
                    "История диалогов",
                    "Возвращайтесь к сохранённому разговору без поиска по техническим идентификаторам.",
                )
                action_button(
                    "Обновить",
                    icon="o_refresh",
                    on_click=load_sessions,
                    variant="secondary",
                )
        with panel(variant="plain", classes="sov-history-list-panel"):
            with ui.row().classes("sov-history-list-head"):
                section_heading("Сохранённые диалоги", "Сначала показаны последние 50 сессий.")
                status_badge("read-only", "muted")
            refs["sessions"] = ui.column().classes("sov-history-list")

    asyncio.create_task(load_sessions())
