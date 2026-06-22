"""
С.О.В.У.Ш.К.А. — специализированный артефакт ВЕРИФИКАЦИИ объёмов.

Не отдельная вкладка, а артефакт чата (как визуализатор Клода): чат распознаёт
таблицу со скана и открывает в панели — СКАН сверху (во всю ширину), РАСПОЗНАННАЯ
таблица снизу (правится в ячейках). Оператор подтверждает «всё ок» / правит /
отклоняет; результат → /api/verify/save (принятая выписка + ground truth для бенча).

ВЫДЕЛЕНИЕ РЕГИОНА: на больших листах-чертежах таблица — лишь часть листа. Оператор
тащит мышью прямоугольник по скану и жмёт «Извлечь выделенное» → vision получает
только выделение, крупно, без шума плана. Координаты выделения (0..1) уходят в
/api/verify/extract region. Скан показывается same-origin роутом /verify-image.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from nicegui import ui

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
    img_w = int(payload.get("img_w") or 0)
    img_h = int(payload.get("img_h") or 0)
    img_src = f"/verify-image?token={token}" if token else ""

    if not img_src and not rows:
        ui.label("нет данных — повтори «проверь объёмы …»").style("color:var(--err);font-size:.8rem;")
        return

    # состояние выделения (в координатах натуральной картинки)
    sel = {"x0": None, "y0": None, "x1": None, "y1": None, "down": False}

    with ui.column().classes("w-full gap-2"):
        # ── ТИП документа (классификатор: ведомость/экспликация/журнал/…) ──
        type_badge = ui.html("").classes("w-full")

        def _set_type(dt: Optional[dict]) -> None:
            dt = dt or {}
            label = dt.get("label") or "тип не распознан"
            known = dt.get("type") and dt.get("type") != "неизвестно"
            color = "#5ac878" if known else "#c79a3a"
            about = f" · {dt.get('about')}" if dt.get("about") else ""
            tr = f" · название: «{dt.get('title_read')}»" if dt.get("title_read") else ""
            type_badge.content = (
                f'<div style="display:inline-block;padding:3px 10px;border-radius:8px;'
                f'background:rgba(90,200,120,0.10);border:1px solid {color};color:{color};'
                f'font-size:.72rem;font-weight:800">📄 {label}'
                f'<span style="color:var(--dim);font-weight:500">{about} '
                f'(conf {dt.get("confidence", "—")}){tr}</span></div>'
            )

        _set_type(payload.get("doc_type"))

        # ── СКАН с выделением региона ──
        with ui.row().classes("items-center gap-2 w-full"):
            ui.label("СКАН").classes("sov-panel-title")
            ui.label("— тащи мышью рамку по таблице на чертеже").style(
                "font-size:.62rem;color:var(--dim);"
            )

        if img_src:
            ii = ui.interactive_image(
                img_src, events=["mousedown", "mousemove", "mouseup"], cross="#5aa0ff"
            ).classes("w-full").style(
                "max-height:46vh;border:1px solid var(--border);border-radius:6px;background:#0b0d12;"
            )

            def _draw() -> None:
                if sel["x0"] is None:
                    ii.content = ""
                    return
                x = min(sel["x0"], sel["x1"]); y = min(sel["y0"], sel["y1"])
                w = abs(sel["x1"] - sel["x0"]); h = abs(sel["y1"] - sel["y0"])
                ii.content = (
                    f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                    f'fill="rgba(90,160,255,0.16)" stroke="#5aa0ff" stroke-width="6"/>'
                )

            def _mouse(e) -> None:
                if e.type == "mousedown":
                    sel.update(x0=e.image_x, y0=e.image_y, x1=e.image_x, y1=e.image_y, down=True)
                elif e.type == "mousemove" and sel["down"]:
                    sel.update(x1=e.image_x, y1=e.image_y)
                elif e.type == "mouseup":
                    sel.update(x1=e.image_x, y1=e.image_y, down=False)
                _draw()

            ii.on_mouse(_mouse)
        else:
            ui.label("скан не загрузился").style("color:var(--dim);padding:10px;display:block;")

        def _region() -> Optional[list]:
            if sel["x0"] is None or not img_w or not img_h:
                return None
            x0 = min(sel["x0"], sel["x1"]) / img_w; x1 = max(sel["x0"], sel["x1"]) / img_w
            y0 = min(sel["y0"], sel["y1"]) / img_h; y1 = max(sel["y0"], sel["y1"]) / img_h
            if x1 - x0 < 0.01 or y1 - y0 < 0.01:
                return None
            return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]

        # ── контейнер распознанной таблицы (перерисовывается при extract по региону) ──
        table_box = ui.column().classes("w-full gap-2")

        async def _extract_region() -> None:
            reg = _region()
            if reg is None:
                rstatus.text = "выдели рамку на скане (тащи мышью)"
                return
            rstatus.text = "извлекаю выделенное…"
            res = await api_post(
                "/api/verify/extract", {"path": source, "page": page, "region": reg}
            )
            if isinstance(res, dict) and res.get("rows") is not None:
                _set_type(res.get("doc_type"))
                _render_table(res.get("rows") or [], res.get("columns") or [])
                rstatus.text = f"из выделенного: {len(res.get('rows') or [])} строк"
                add_log(f"[ВЕРИФ] регион {reg} → {len(res.get('rows') or [])} строк")
            else:
                rstatus.text = "не удалось извлечь выделенное"

        def _clear_sel() -> None:
            sel.update(x0=None, y0=None, x1=None, y1=None, down=False)
            if img_src:
                ii.content = ""
            rstatus.text = ""

        with ui.row().classes("items-center gap-2 w-full flex-wrap"):
            ui.button("⤵ Извлечь выделенное", on_click=lambda: asyncio.create_task(_extract_region())).props(
                "dense"
            ).style("background:var(--accent);color:#08110a;font-weight:800;")
            ui.button("Сбросить рамку", on_click=_clear_sel).props("dense flat")
            rstatus = ui.label("").style("font-size:.7rem;color:var(--dim);")

        # ── рендер таблицы (шапка-инпуты + грид + вердикт); перерисовываемо ──
        ACC = "Принято (объём)"  # колонка приёмки: рукопись с галочками vision не читает → правит оператор

        def _render_table(trows: list, tcols: list) -> None:
            table_box.clear()
            tcols = tcols or (list(trows[0].keys()) if trows and isinstance(trows[0], dict) else [])
            # графа количества → добавляем «Принято», преднаполняя печатным Кол-во
            qty = next((c for c in tcols if "кол" in str(c).lower()), None)
            add_acc = bool(qty) and ACC not in tcols
            disp_cols = list(tcols) + ([ACC] if add_acc else [])
            disp_rows = []
            for r in trows:
                rr = dict(r)
                if add_acc:
                    rr[ACC] = rr.get(qty, "")
                disp_rows.append(rr)
            with table_box:
                ui.label("РАСПОЗНАНО — правь шапку и ячейки").classes("sov-panel-title")
                if add_acc:
                    ui.label(
                        "«Принято» (зелёная графа) = принятый объём: преднаполнено печатным Кол-во; "
                        "правь, где на скане рукопись/исправление (галочка = принято как есть)."
                    ).style("font-size:.6rem;color:var(--dim);")
                header_inputs: list = []
                with ui.row().classes("w-full gap-1 flex-wrap").style("margin-bottom:2px;"):
                    ui.label("шапка:").style("font-size:.62rem;color:var(--dim);align-self:center;")
                    for c in tcols:  # переименовываемы только реальные графы (не служебное «Принято»)
                        inp = ui.input(value=c).props("dense outlined").style(
                            "width:120px;font-size:.66rem;"
                        )
                        header_inputs.append((c, inp))
                coldefs = [{"headerName": c, "field": c, "minWidth": 120} for c in disp_cols] or [
                    {"headerName": "значение", "field": "value"}
                ]
                for cd in coldefs:  # подсветить колонку приёмки
                    if cd.get("field") == ACC:
                        cd["cellStyle"] = {"backgroundColor": "rgba(90,200,120,0.14)", "fontWeight": "700"}
                        cd["pinned"] = "right"
                        cd["minWidth"] = 130
                grid = ui.aggrid({
                    "columnDefs": coldefs,
                    "rowData": disp_rows,
                    "defaultColDef": {"editable": True, "resizable": True, "sortable": True, "minWidth": 110},
                    "singleClickEdit": True,
                }).classes("w-full").style("height:40vh;")

                async def _save(verdict: str) -> None:
                    data = await grid.get_client_data()
                    rename = {orig: (inp.value or orig).strip() for orig, inp in header_inputs}
                    data = [{rename.get(k, k): v for k, v in row.items()} for row in data]
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
                    data.append({c: "" for c in tcols})
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

        _render_table(rows, columns)
