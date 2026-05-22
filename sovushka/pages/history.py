"""
С.О.В.У.Ш.К.А. v5.0 — Вкладка ИСТОРИЯ ЧАТОВ
"""
from __future__ import annotations

import asyncio
from nicegui import ui, app

from sovushka.state import state, api_get, add_log
from sovushka.components.charts import _html


def build_history(tabs=None, tab_chat=None):
    """Строит содержимое вкладки ИСТОРИЯ. Вызывать внутри with ui.tab_panel(...)."""

    with ui.column().classes("w-full h-full gap-3 p-4"):

        # Заголовок
        with ui.row().classes("w-full items-center gap-3"):
            _html('<div style="font-size:1rem;font-weight:700;color:var(--accent);letter-spacing:.1em;">ИСТОРИЯ ЧАТОВ</div>')
            refresh_btn = ui.button("↺ ОБНОВИТЬ", icon="o_refresh").props("flat dense").classes("text-xs")
            refresh_btn.style("color:var(--dim);font-size:.7rem;")

        sessions_col = ui.column().classes("w-full gap-2")

        async def _load_sessions():
            sessions_col.clear()
            data = await api_get("/api/chat/sessions?limit=50")
            if not data:
                with sessions_col:
                    _html('<div style="color:var(--dim);font-size:.8rem;padding:16px;">Нет сохранённых сессий</div>')
                return
            with sessions_col:
                for s in data:
                    _render_session_card(s)

        def _render_session_card(s: dict):
            sid        = s["session_id"]
            first_q    = s["first_question"] or "—"
            msg_count  = s["msg_count"]
            started_at = (s["started_at"] or "")[:16].replace("T", " ")
            last_at    = (s["last_at"]    or "")[:16].replace("T", " ")

            with ui.card().classes("w-full cursor-pointer").style(
                "background:var(--bg-panel);border:1px solid var(--border);"
                "border-radius:6px;padding:12px 16px;transition:border-color .15s;"
            ) as card:
                card.style("cursor:pointer;")
                with ui.row().classes("w-full items-start justify-between gap-2"):
                    with ui.column().classes("flex-1 gap-1"):
                        _html(
                            f'<div style="font-size:.8rem;color:var(--text);font-weight:600;">'
                            f'{first_q[:100]}{"…" if len(first_q)>100 else ""}'
                            f'</div>'
                        )
                        _html(
                            f'<div style="font-size:.68rem;color:var(--dim);">'
                            f'{started_at} &nbsp;·&nbsp; {msg_count} сообщ.'
                            f'{"&nbsp;·&nbsp;последнее " + last_at if last_at != started_at else ""}'
                            f'</div>'
                        )
                    open_btn = ui.button("Открыть →").props("flat dense").classes("text-xs self-center")
                    open_btn.style("color:var(--accent);font-size:.68rem;")

                async def _open(session_id=sid):
                    await _open_session(session_id)

                card.on("click", _open)
                open_btn.on("click", _open)

        async def _open_session(session_id: str):
            """Загружает сессию в state и переключает на вкладку чата."""
            add_log(f"[ИСТОРИЯ] Загружаю сессию {session_id[:8]}…")
            msgs = await api_get(f"/api/chat/history?session_id={session_id}")
            if msgs is None:
                add_log("[ИСТОРИЯ] Ошибка загрузки сессии")
                return
            # Сохраняем в state — вкладка чата подхватит при следующем рендере
            state["chat_history"] = msgs
            state["load_session_id"] = session_id
            add_log(f"[ИСТОРИЯ] Загружено {len(msgs)//2} сообщений")
            # Переключаем на вкладку чата
            if tabs and tab_chat:
                tabs.set_value(tab_chat)

        refresh_btn.on("click", lambda: asyncio.create_task(_load_sessions()))

        # Загружаем сессии при открытии вкладки
        ui.timer(0.3, lambda: asyncio.create_task(_load_sessions()), once=True)
