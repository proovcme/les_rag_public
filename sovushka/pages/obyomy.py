"""
С.О.В.У.Ш.К.А. — Вкладка ОБЪЁМЫ (W8.1/W8.4: журнал полевых объёмов).

Те же данные, что у чат-команды «запиши объём 50 м3 …» и вопросов «сколько …
выполнено за период …» — /api/field. Числа считает SQL (ADR-11), не LLM.
"""
from __future__ import annotations

import asyncio

from nicegui import ui

from sovushka.state import add_log, api_delete, api_get, api_get_bytes, api_patch, api_post

_STATUS_LABEL = {"confirmed": "✓ подтв.", "pending": "◐ на проверке", "rejected": "✗ откл."}


def build_obyomy():
    """Строит содержимое вкладки ОБЪЁМЫ. Вызывать внутри with ui.tab_panel(tab_obyomy)."""
    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("ОБЪЁМЫ // ЖУРНАЛ ПОЛЕВЫХ ОБЪЁМОВ").style(
                "font-size:1rem;font-weight:900;letter-spacing:1px;"
            )
            ui.label("чат: «запиши объём 50 м3 …» · «сколько … за июнь?»").style(
                "font-size:.6rem;color:var(--dim);"
            )

        # ── Ввод записи ──
        with ui.card().classes("card-les w-full"):
            ui.label("НОВАЯ ЗАПИСЬ").classes("section-title")
            with ui.row().classes("w-full gap-2 items-center flex-wrap"):
                in_pos = ui.input(placeholder="позиция / наименование работы").classes("flex-1").props("dense outlined")
                in_vol = ui.number(label="объём", format="%.3f").props("dense outlined").style("width:110px;")
                in_unit = ui.input(placeholder="ед.").props("dense outlined").style("width:80px;")
                in_zah = ui.input(placeholder="захватка").props("dense outlined").style("width:110px;")
                in_date = ui.input(placeholder="дата ГГГГ-ММ-ДД").props("dense outlined").style("width:140px;")
                ui.button("ДОБАВИТЬ", on_click=lambda: asyncio.create_task(_create())).props("dense")
            with ui.row().classes("w-full gap-2 items-center flex-wrap"):
                in_doc = ui.input(placeholder="чертёж (doc_id, необяз.)").props("dense outlined").classes("flex-1")
                in_elem = ui.input(placeholder="элемент BIM (source_id, необяз.)").props("dense outlined").classes("flex-1")

        # ── Свод / отчёт ──
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between w-full gap-3"):
                ui.label("СВОД (только подтверждённые)").classes("section-title")
                ui.button("ЭКСПОРТ XLSX", on_click=lambda: asyncio.create_task(_export())).props("dense flat")
            with ui.row().classes("w-full gap-2 items-center flex-wrap"):
                f_zah = ui.input(placeholder="захватка").props("dense outlined").style("width:120px;")
                f_pos = ui.input(placeholder="позиция").props("dense outlined").style("width:160px;")
                f_from = ui.input(placeholder="с ГГГГ-ММ-ДД").props("dense outlined").style("width:140px;")
                f_to = ui.input(placeholder="по ГГГГ-ММ-ДД").props("dense outlined").style("width:140px;")
                ui.button("СВОД", on_click=lambda: asyncio.create_task(_refresh())).props("dense flat")
            summary_box = ui.column().classes("w-full gap-1")

        # ── Журнал ──
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between w-full gap-3"):
                ui.label("ЖУРНАЛ ЗАПИСЕЙ").classes("section-title")
                show_all = ui.switch("показывать на проверке/отклонённые", value=False)
            entries_box = ui.column().classes("w-full gap-1")

        # ── Обновление ──
        async def _refresh():
            params = []
            if f_zah.value:
                params.append(f"zahvatka={f_zah.value}")
            if f_pos.value:
                params.append(f"position={f_pos.value}")
            if f_from.value:
                params.append(f"date_from={f_from.value}")
            if f_to.value:
                params.append(f"date_to={f_to.value}")
            qs = ("&" + "&".join(params)) if params else ""
            summary = await api_get(f"/api/field/summary?status=confirmed{qs}") or {}
            rows = summary.get("rows", [])
            summary_box.clear()
            with summary_box:
                if not rows:
                    ui.label("записей нет").style("font-size:.7rem;color:var(--dim);")
                else:
                    with ui.row().classes("w-full gap-2").style("border-bottom:1px solid var(--dim);font-weight:700;"):
                        ui.label("Позиция").classes("flex-1").style("font-size:.7rem;")
                        ui.label("Ед.").style("width:60px;font-size:.7rem;")
                        ui.label("Объём").style("width:110px;text-align:right;font-size:.7rem;")
                        ui.label("Зап.").style("width:50px;text-align:right;font-size:.7rem;")
                    for r in rows:
                        with ui.row().classes("w-full gap-2").style("border-bottom:1px dashed var(--dim);padding:1px 0;"):
                            ui.label(r["position"]).classes("flex-1").style("font-size:.72rem;")
                            ui.label(r["unit"] or "—").style("width:60px;font-size:.72rem;color:var(--dim);")
                            ui.label(_fmt(r["total"])).style("width:110px;text-align:right;font-size:.72rem;font-weight:700;")
                            ui.label(str(r["entries"])).style("width:50px;text-align:right;font-size:.72rem;color:var(--dim);")

            data = await api_get("/api/field?limit=200") or {}
            entries = data.get("entries", [])
            if not show_all.value:
                entries = [e for e in entries if e.get("status") == "confirmed"]
            entries_box.clear()
            with entries_box:
                if not entries:
                    ui.label("журнал пуст").style("font-size:.7rem;color:var(--dim);")
                for e in entries:
                    with ui.row().classes("w-full items-center gap-2").style("border-bottom:1px dashed var(--dim);padding:2px 0;"):
                        ui.label(e["entry_date"]).style("width:92px;font-size:.68rem;color:var(--dim);flex-shrink:0;")
                        label = f"#{e['id']} {e['position']}"
                        if e["zahvatka"]:
                            label += f" · захв. {e['zahvatka']}"
                        ui.label(label).classes("flex-1").style("font-size:.74rem;")
                        ui.label(f"{_fmt(e['volume'])} {e['unit']}").style("width:120px;text-align:right;font-size:.74rem;font-weight:700;")
                        ui.label(_STATUS_LABEL.get(e["status"], e["status"])).style("width:96px;font-size:.62rem;color:var(--dim);")
                        if e["status"] != "confirmed":
                            ui.button("✓", on_click=lambda eid=e["id"]: asyncio.create_task(_set_status(eid, "confirmed"))).props("dense flat").style("color:var(--ok);")
                        ui.button("✗", on_click=lambda eid=e["id"]: asyncio.create_task(_delete(eid))).props("dense flat").style("color:var(--err);")

        # ── Обработчики ──
        async def _create():
            pos = (in_pos.value or "").strip()
            if not pos or in_vol.value is None:
                add_log("[ОБЪЁМЫ] нужны позиция и объём")
                return
            await api_post("/api/field", {
                "position": pos,
                "volume": float(in_vol.value),
                "unit": (in_unit.value or "").strip(),
                "zahvatka": (in_zah.value or "").strip(),
                "entry_date": (in_date.value or "").strip(),
                "doc_id": (in_doc.value or "").strip(),
                "element_id": (in_elem.value or "").strip(),
            })
            add_log(f"[ОБЪЁМЫ] запись: {pos[:50]} {in_vol.value} {in_unit.value or ''}")
            in_pos.value = ""
            in_vol.value = None
            in_zah.value = ""
            await _refresh()

        async def _set_status(entry_id: int, status: str):
            await api_patch(f"/api/field/{entry_id}", {"status": status})
            await _refresh()

        async def _delete(entry_id: int):
            await api_delete(f"/api/field/{entry_id}")
            await _refresh()

        async def _export():
            res = await api_post("/api/field/export", {})
            if not res:
                add_log("[ОБЪЁМЫ] экспорт не удался")
                return
            blob = await api_get_bytes("/api/field/download")
            if blob:
                content, fname = blob
                ui.download(content, fname)
                add_log(f"[ОБЪЁМЫ] экспортировано записей: {res.get('rows', 0)}")

        show_all.on_value_change(lambda _: asyncio.create_task(_refresh()))
        ui.timer(0.1, lambda: asyncio.create_task(_refresh()), once=True)


def _fmt(value) -> str:
    try:
        return f"{float(value):.3f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)
