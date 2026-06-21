"""
С.О.В.У.Ш.К.А. — Вкладка ВЕРИФИКАЦИЯ.

Сплит: слева рендер страницы скана таблицы объёмов, справа — распознанная таблица
(правится прямо в ячейках). Оператора спрашивают «всё ли ок». Подтверждённый/
исправленный результат сохраняется через /api/verify/save и становится:
  - принятой выпиской объёмов (рабочая функция);
  - ground truth для бенча извлечения (tools/extract_bench.py).
То есть верификация = заодно разметка. Бэкенд — proxy/services/verify_service.
"""
from __future__ import annotations

import asyncio

from nicegui import ui

from sovushka.config import PROXY_URL
from sovushka.state import add_log, api_post


def build_verify():
    """Содержимое вкладки ВЕРИФИКАЦИЯ. Вызывать внутри with ui.tab_panel(...)."""
    state = {"token": None, "path": None, "page": 0}

    with ui.column().classes("w-full h-full p-3 gap-2"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("ВЕРИФИКАЦИЯ ОБЪЁМОВ // скан ↔ распознанное").style(
                "font-size:1rem;font-weight:900;letter-spacing:1px;"
            )
            ui.label("проверь таблицу справа против скана слева и подтверди").style(
                "font-size:.6rem;color:var(--dim);"
            )

        # ── панель ввода ──
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("w-full gap-2 items-center flex-wrap"):
                in_path = ui.input(placeholder="путь к скану (PDF / изображение)").props(
                    "dense outlined"
                ).classes("flex-1")
                in_page = ui.number(label="стр.", value=0, format="%d").props(
                    "dense outlined"
                ).style("width:90px;")
                in_engine = ui.select(
                    {"local": "локально (vision)", "cloud": "облако"}, value="local"
                ).props("dense outlined").style("width:170px;")
                ui.button(
                    "РАСПОЗНАТЬ", on_click=lambda: asyncio.create_task(_extract())
                ).props("dense")

        # ── сплит: скан | таблица ──
        with ui.row().classes("w-full gap-2 no-wrap").style("min-height:62vh;"):
            with ui.card().classes("card-les").style("flex:1;overflow:auto;"):
                ui.label("СКАН").classes("section-title")
                img = ui.image("").classes("w-full").style(
                    "border:1px solid var(--border);border-radius:6px;background:#0b0d12;"
                )
            with ui.card().classes("card-les").style("flex:1;overflow:auto;"):
                with ui.row().classes("items-center justify-between w-full"):
                    ui.label("РАСПОЗНАННАЯ ТАБЛИЦА (правится в ячейках)").classes("section-title")
                    ui.button(
                        "+ строка", on_click=lambda: asyncio.create_task(_add_row())
                    ).props("dense flat")
                grid = ui.aggrid(
                    {
                        "columnDefs": [],
                        "rowData": [],
                        "defaultColDef": {"editable": True, "resizable": True, "sortable": True},
                        "singleClickEdit": True,
                    }
                ).classes("w-full").style("height:56vh;")

        # ── вердикт ──
        with ui.row().classes("items-center gap-2 w-full"):
            ui.button("✓ ВСЁ ОК", on_click=lambda: asyncio.create_task(_save("ok"))).props(
                "dense"
            ).style("background:var(--ok);color:#08110a;font-weight:800;")
            ui.button(
                "💾 СОХРАНИТЬ ПРАВКИ", on_click=lambda: asyncio.create_task(_save("corrected"))
            ).props("dense outline")
            ui.button(
                "✗ ОТКЛОНИТЬ", on_click=lambda: asyncio.create_task(_save("rejected"))
            ).props("dense flat").style("color:var(--err);")
            status = ui.label("").style("font-size:.72rem;color:var(--dim);")

        # ── обработчики ──
        async def _extract():
            path = (in_path.value or "").strip()
            if not path:
                add_log("[ВЕРИФ] укажи путь к скану")
                return
            page = int(in_page.value or 0)
            status.text = "распознаю…"
            res = await api_post(
                "/api/verify/extract", {"path": path, "page": page, "engine": in_engine.value}
            )
            if not res:
                status.text = "ошибка распознавания (см. лог)"
                return
            state.update(token=res["token"], path=path, page=page)
            img.set_source(f"{PROXY_URL}/api/verify/image?token={res['token']}")
            cols = res.get("columns") or []
            grid.options["columnDefs"] = (
                [{"headerName": c, "field": c} for c in cols]
                or [{"headerName": "значение", "field": "value"}]
            )
            grid.options["rowData"] = res.get("rows") or []
            grid.update()
            n = len(res.get("rows") or [])
            status.text = f"строк: {n} — сверь со сканом и поправь"
            add_log(f"[ВЕРИФ] распознано {n} строк: {path} стр.{page}")

        async def _add_row():
            if not grid.options["columnDefs"]:
                return
            data = await grid.get_client_data()
            cols = [c["field"] for c in grid.options["columnDefs"]]
            data.append({c: "" for c in cols})
            grid.options["rowData"] = data
            grid.update()

        async def _save(verdict: str):
            if not state["token"]:
                add_log("[ВЕРИФ] нечего сохранять — сначала распознай")
                return
            rows = await grid.get_client_data()
            res = await api_post(
                "/api/verify/save",
                {"path": state["path"], "page": state["page"], "rows": rows, "verdict": verdict},
            )
            if res and res.get("ok"):
                status.text = f"сохранено ({verdict}): {res.get('n_rows')} строк"
                add_log(
                    f"[ВЕРИФ] {verdict}: {state['path']} стр.{state['page']} — {res.get('n_rows')} строк"
                )
            else:
                status.text = "сохранить не удалось"
