"""
С.О.В.У.Ш.К.А. — специализированный артефакт ВЕРИФИКАЦИИ объёмов.

Не отдельная вкладка, а артефакт чата (как визуализатор Клода): чат распознаёт
таблицу объёмов со скана и открывает в панели артефактов — СКАН сверху (во всю
ширину панели, читаемо), РАСПОЗНАННАЯ таблица снизу (правится в ячейках, все
колонки видны). Оператор подтверждает «всё ок» / правит / отклоняет; результат
уходит в /api/verify/save → принятая выписка + ground truth для бенча.

Картинка приходит инлайн (data-URI в payload.image_b64) — без кросс-origin/порта/
куки. Рендерится в ТЕКУЩИЙ ui-контекст карточки артефакта (chat._render_result).
"""
from __future__ import annotations

import asyncio
from typing import Optional

from nicegui import ui

from sovushka.config import PROXY_URL
from sovushka.state import add_log, api_post


def render_verify_artifact(payload: Optional[dict]) -> None:
    payload = payload or {}
    token = payload.get("token") or ""
    source = payload.get("source") or ""
    page = int(payload.get("page") or 0)
    rows = payload.get("rows") or []
    columns = payload.get("columns") or (
        list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
    )
    # картинка — same-origin роутом Совушки (/verify-image), без кросс-порта/base64 в payload
    img_src = f"/verify-image?token={token}" if token else ""

    if not img_src and not rows:
        ui.label("нет данных — повтори «проверь объёмы …»").style("color:var(--err);font-size:.8rem;")
        return

    with ui.column().classes("w-full gap-2"):
        # ── СКАН (сверху, во всю ширину панели) ──
        ui.label("СКАН").classes("sov-panel-title")
        if img_src:
            # обычный <img> (не q-img — тот схлопывается в 0 высоты)
            ui.html(
                f'<div style="max-height:46vh;overflow:auto;border:1px solid var(--border);'
                f'border-radius:6px;background:#0b0d12">'
                f'<img src="{img_src}" style="width:100%;display:block" '
                f'alt="скан"/></div>'
            ).classes("w-full")
        else:
            ui.label("скан не загрузился").style("color:var(--dim);padding:10px;display:block;")

        # ── РАСПОЗНАНО (снизу, во всю ширину, все колонки) ──
        ui.label("РАСПОЗНАНО — правится в ячейках").classes("sov-panel-title")
        grid = ui.aggrid({
            "columnDefs": [{"headerName": c, "field": c, "minWidth": 120} for c in columns]
                          or [{"headerName": "значение", "field": "value"}],
            "rowData": rows,
            "defaultColDef": {"editable": True, "resizable": True, "sortable": True, "minWidth": 110},
            "singleClickEdit": True,
        }).classes("w-full").style("height:44vh;")

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
