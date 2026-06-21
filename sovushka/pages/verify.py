"""
С.О.В.У.Ш.К.А. — специализированный артефакт ВЕРИФИКАЦИИ объёмов.

Не отдельная вкладка, а артефакт чата (как визуализатор Клода): чат распознаёт
таблицу объёмов со скана и открывает в панели артефактов сплит — слева рендер
скана, справа распознанная таблица (правится в ячейках). Оператор подтверждает
«всё ок» / правит / отклоняет; результат уходит в /api/verify/save и становится
принятой выпиской + ground truth для бенча извлечения.

Рендерится в ТЕКУЩИЙ ui-контекст (внутри карточки артефакта в chat._render_result).
Бэкенд — proxy/services/verify_service.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from nicegui import ui

from sovushka.config import PROXY_URL
from sovushka.state import add_log, api_post


def render_verify_artifact(payload: Optional[dict]) -> None:
    """Нарисовать сплит «скан ↔ распознанное» из payload {token, rows, columns, source, page}."""
    payload = payload or {}
    token = payload.get("token") or ""
    source = payload.get("source") or ""
    page = int(payload.get("page") or 0)
    rows = payload.get("rows") or []
    columns = payload.get("columns") or (list(rows[0].keys()) if rows and isinstance(rows[0], dict) else [])

    if not token:
        ui.label("нет рендера скана — повтори «проверь объёмы …»").style("color:var(--err);font-size:.75rem;")
        return

    with ui.column().classes("w-full gap-2"):
        # ── сплит ──
        with ui.row().classes("w-full gap-2 no-wrap").style("min-height:48vh;"):
            with ui.column().style("flex:1;min-width:0;overflow:auto;"):
                ui.label("СКАН").classes("sov-panel-title")
                ui.image(f"{PROXY_URL}/api/verify/image?token={token}").classes("w-full").style(
                    "border:1px solid var(--border);border-radius:6px;background:#0b0d12;"
                )
            with ui.column().style("flex:1;min-width:0;overflow:auto;"):
                ui.label("РАСПОЗНАНО (правится в ячейках)").classes("sov-panel-title")
                grid = ui.aggrid({
                    "columnDefs": [{"headerName": c, "field": c} for c in columns]
                                  or [{"headerName": "значение", "field": "value"}],
                    "rowData": rows,
                    "defaultColDef": {"editable": True, "resizable": True, "sortable": True},
                    "singleClickEdit": True,
                }).classes("w-full").style("height:46vh;")

        # ── вердикт ──
        async def _save(verdict: str) -> None:
            data = await grid.get_client_data()
            res = await api_post(
                "/api/verify/save",
                {"path": source, "page": page, "rows": data, "verdict": verdict},
            )
            if res and res.get("ok"):
                status.text = f"сохранено ({verdict}): {res.get('n_rows')} строк"
                add_log(f"[ВЕРИФ] {verdict}: {source} стр.{page} — {res.get('n_rows')} строк")
            else:
                status.text = "не удалось сохранить"

        async def _add_row() -> None:
            data = await grid.get_client_data()
            data.append({c: "" for c in columns})
            grid.options["rowData"] = data
            grid.update()

        with ui.row().classes("items-center gap-2 w-full flex-wrap"):
            ui.button("✓ Всё ок", on_click=lambda: asyncio.create_task(_save("ok"))).props(
                "dense"
            ).style("background:var(--ok);color:#08110a;font-weight:800;")
            ui.button("💾 Сохранить правки", on_click=lambda: asyncio.create_task(_save("corrected"))).props("dense outline")
            ui.button("✗ Отклонить", on_click=lambda: asyncio.create_task(_save("rejected"))).props(
                "dense flat"
            ).style("color:var(--err);")
            ui.button("+ строка", on_click=lambda: asyncio.create_task(_add_row())).props("dense flat")
            status = ui.label("").style("font-size:.72rem;color:var(--dim);")
