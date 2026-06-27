"""
С.О.В.У.Ш.К.А. — Вкладка ЗАДАЧИ (W16.2/W16.3: задачник и заметки оператора).

Те же данные, что у чат-команд «поставь задачу…»/«запомни:…» — /api/tasks и /api/notes.
"""
from __future__ import annotations

import asyncio

from nicegui import ui

from sovushka.state import api_delete, api_get, api_patch, api_post, add_log

_STATUS_LABEL = {"open": "○ открыта", "in_progress": "◐ в работе", "done": "✓ готова", "dropped": "✗ снята"}


def build_zadachi():
    """Строит содержимое вкладки ЗАДАЧИ. Вызывать внутри with ui.tab_panel(tab_zadachi)."""
    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("ЗАДАЧИ // РАБОЧАЯ ПАМЯТЬ").style(
                "font-size:1rem;font-weight:900;letter-spacing:1px;"
            )
            ui.label("чат-команды: «поставь задачу …» · «запомни: …» · «задача N готова»").style(
                "font-size:.6rem;color:var(--dim);"
            )

        # ── Задачи ──
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between w-full gap-3"):
                ui.label("ЗАДАЧНИК").classes("section-title")
                show_done = ui.switch("показывать закрытые", value=False)
            with ui.row().classes("w-full gap-2 items-center"):
                new_task = ui.input(placeholder="новая задача…").classes("flex-1").props("dense outlined")
                ui.button("ДОБАВИТЬ", on_click=lambda: asyncio.create_task(_create_task())).props("dense")
            tasks_box = ui.column().classes("w-full gap-1")

        # ── Заметки ──
        with ui.card().classes("card-les w-full"):
            ui.label("ЗАМЕТКИ ОПЕРАТОРА (подмешиваются в ответы чата)").classes("section-title")
            with ui.row().classes("w-full gap-2 items-center"):
                new_note = ui.input(placeholder="запомнить…").classes("flex-1").props("dense outlined")
                ui.button("ЗАПОМНИТЬ", on_click=lambda: asyncio.create_task(_create_note())).props("dense")
            notes_box = ui.column().classes("w-full gap-1")

        async def _refresh():
            tasks_data = await api_get("/api/tasks?limit=100") or {}
            notes_data = await api_get("/api/notes?limit=100") or {}
            tasks = tasks_data.get("tasks", [])
            if not show_done.value:
                tasks = [t for t in tasks if t.get("status") in ("open", "in_progress")]
            tasks_box.clear()
            with tasks_box:
                if not tasks:
                    ui.label("задач нет").style("font-size:.7rem;color:var(--dim);")
                for t in tasks:
                    with ui.row().classes("w-full items-center gap-2").style(
                        "border-bottom:1px dashed var(--dim);padding:2px 0;"
                    ):
                        ui.label(_STATUS_LABEL.get(t["status"], t["status"])).style(
                            "font-size:.65rem;width:90px;color:var(--dim);flex-shrink:0;"
                        )
                        label = f"#{t['id']} {t['title']}"
                        if t.get("dataset_filter"):
                            label += f" [{t['dataset_filter']}]"
                        ui.label(label).classes("flex-1").style("font-size:.75rem;")
                        if t["status"] in ("open", "in_progress"):
                            ui.button(
                                "✓", on_click=lambda tid=t["id"]: asyncio.create_task(_set_status(tid, "done"))
                            ).props("dense flat").style("color:var(--ok);")
                            ui.button(
                                "✗", on_click=lambda tid=t["id"]: asyncio.create_task(_set_status(tid, "dropped"))
                            ).props("dense flat").style("color:var(--err);")
            notes = notes_data.get("notes", [])
            notes_box.clear()
            with notes_box:
                if not notes:
                    ui.label("заметок нет").style("font-size:.7rem;color:var(--dim);")
                for n in notes:
                    with ui.row().classes("w-full items-center gap-2").style(
                        "border-bottom:1px dashed var(--dim);padding:2px 0;"
                    ):
                        ui.label(f"✎ #{n['id']} {n['text']}").classes("flex-1").style("font-size:.75rem;")
                        ui.button(
                            "✗", on_click=lambda nid=n["id"]: asyncio.create_task(_del_note(nid))
                        ).props("dense flat").style("color:var(--err);")

        async def _create_task():
            title = (new_task.value or "").strip()
            if len(title) < 3:
                return
            await api_post("/api/tasks", {"title": title})
            new_task.value = ""
            add_log(f"[ЗАДАЧИ] создана: {title[:60]}")
            await _refresh()

        async def _set_status(task_id: int, status: str):
            await api_patch(f"/api/tasks/{task_id}", {"status": status})
            await _refresh()

        async def _create_note():
            text = (new_note.value or "").strip()
            if len(text) < 3:
                return
            await api_post("/api/notes", {"text": text})
            new_note.value = ""
            add_log(f"[ЗАМЕТКИ] создана: {text[:60]}")
            await _refresh()

        async def _del_note(note_id: int):
            await api_delete(f"/api/notes/{note_id}")
            await _refresh()

        show_done.on_value_change(lambda _: asyncio.create_task(_refresh()))
        ui.timer(0.1, lambda: asyncio.create_task(_refresh()), once=True)
