"""
С.О.В.У.Ш.К.А. — Вкладка ИНСТРУМЕНТЫ: детерминированные функции по документам в GUI.

ВОР (ведомости объёмов), нормоконтроль, дифф ревизий — всё, что раньше было
только через curl. 0 LLM на бэке (см. сервисы bor/normcontrol/diff).
"""
from __future__ import annotations

import asyncio

from nicegui import ui

from sovushka.state import (
    add_log,
    api_get,
    api_get_bytes,
    api_post,
    last_api_error_text,
)

_SEV_COLOR = {"error": "var(--err)", "warning": "#d6a400", "info": "var(--dim)"}


async def _datasets() -> list[dict]:
    ds = await api_get("/api/rag/datasets") or []
    return ds if isinstance(ds, list) else ds.get("datasets", [])


def _ds_options(ds_list: list[dict]) -> dict[str, str]:
    return {d.get("id") or d.get("dataset_id"): d.get("name", "?") for d in ds_list}


async def _download(path: str):
    res = await api_get_bytes(path)
    if not res:
        ui.notify(last_api_error_text("Файл не готов"), type="negative")
        return
    data, fname = res
    ui.download(data, fname)


def build_instrumenty():
    """Содержимое вкладки ИНСТРУМЕНТЫ. Вызывать внутри with ui.tab_panel(...)."""
    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
        ui.label("ИНСТРУМЕНТЫ // ДЕТЕРМИНИРОВАННЫЕ ФУНКЦИИ (0 LLM)").style(
            "font-size:1rem;font-weight:900;letter-spacing:1px;"
        )

        # ─────────────────────────── ВОР ───────────────────────────
        with ui.card().classes("card-les w-full"):
            ui.label("ВЕДОМОСТЬ ОБЪЁМОВ РАБОТ (ВОР) ИЗ СПЕЦИФИКАЦИЙ").classes("section-title")
            with ui.row().classes("w-full gap-2 items-center"):
                bor_ds = ui.select(options={}, label="Датасет со спецификациями").props(
                    "dense outlined"
                ).classes("flex-1")
                ui.button("СФОРМИРОВАТЬ", on_click=lambda: asyncio.create_task(_bor_generate())).props("dense no-caps")
                ui.button("СКАЧАТЬ XLSX", on_click=lambda: asyncio.create_task(
                    _download(f"/api/bor/{bor_ds.value}/download")
                )).props("dense flat no-caps")
            bor_summary = ui.label("").style("font-size:.7rem;color:var(--dim);")
            bor_tbl = ui.table(
                columns=[
                    {"name": "section", "label": "Раздел", "field": "section", "align": "left"},
                    {"name": "name", "label": "Наименование", "field": "name", "align": "left"},
                    {"name": "mark", "label": "Марка", "field": "mark", "align": "left"},
                    {"name": "unit", "label": "Ед.", "field": "unit", "align": "center"},
                    {"name": "qty", "label": "Кол-во", "field": "qty", "align": "right"},
                ],
                rows=[], row_key="name",
            ).classes("w-full").style("font-size:.72rem;")

            async def _bor_generate():
                if not bor_ds.value:
                    ui.notify("Выбери датасет", type="warning")
                    return
                add_log(f"[ВОР] generate {bor_ds.value}")
                d = await api_post(f"/api/bor/{bor_ds.value}/generate")
                if not d:
                    ui.notify(last_api_error_text("ВОР: нет строк спецификаций"), type="negative")
                    return
                ui.notify(f"ВОР: {d.get('bor_lines',0)} строк из {d.get('source_rows',0)} исходных", type="positive")
                prev = await api_get(f"/api/bor/{bor_ds.value}/preview?limit=200") or {}
                bor_summary.text = f"Строк ВОР: {prev.get('bor_lines',0)} · исходных: {prev.get('source_rows',0)}"
                bor_tbl.rows = prev.get("lines", [])
                bor_tbl.update()

        # ───────────────────────── НОРМОКОНТРОЛЬ ─────────────────────────
        with ui.card().classes("card-les w-full"):
            ui.label("ФОРМАЛЬНЫЙ НОРМОКОНТРОЛЬ (NK-01…NK-04, ГОСТ)").classes("section-title")
            with ui.row().classes("w-full gap-2 items-center"):
                nc_ds = ui.select(options={}, label="Датасет с PDF-листами").props(
                    "dense outlined"
                ).classes("flex-1")
                ui.button("ПРОВЕРИТЬ", on_click=lambda: asyncio.create_task(_nc_run())).props("dense no-caps")
                ui.button("СКАЧАТЬ ОТЧЁТ", on_click=lambda: asyncio.create_task(
                    _download(f"/api/normcontrol/{nc_ds.value}/download")
                )).props("dense flat no-caps")
            nc_summary = ui.label("").style("font-size:.7rem;color:var(--dim);")
            nc_tbl = ui.table(
                columns=[
                    {"name": "check", "label": "Проверка", "field": "check", "align": "left"},
                    {"name": "severity", "label": "Уровень", "field": "severity", "align": "center"},
                    {"name": "target", "label": "Файл/лист", "field": "target", "align": "left"},
                    {"name": "message", "label": "Замечание", "field": "message", "align": "left"},
                ],
                rows=[], row_key="message",
            ).classes("w-full").style("font-size:.72rem;")

            async def _nc_run():
                if not nc_ds.value:
                    ui.notify("Выбери датасет", type="warning")
                    return
                add_log(f"[НК] run {nc_ds.value}")
                d = await api_post(f"/api/normcontrol/{nc_ds.value}/run")
                if not d:
                    ui.notify(last_api_error_text("Нормоконтроль: нет PDF"), type="negative")
                    return
                nc_summary.text = (
                    f"Проверено файлов: {d.get('files_checked',0)} · "
                    f"замечаний: {d.get('findings_total',0)} "
                    f"(ошибок {d.get('errors',0)}, предупр. {d.get('warnings',0)})"
                )
                nc_tbl.rows = d.get("findings", [])
                nc_tbl.update()
                ui.notify(nc_summary.text, type="positive" if not d.get("errors") else "warning")

        # ─────────────────────────── ДИФФ ───────────────────────────
        with ui.card().classes("card-les w-full"):
            ui.label("ДИФФ РЕВИЗИЙ (CAD/BIM-модель · текст документа)").classes("section-title")
            with ui.row().classes("w-full gap-2 items-center"):
                imp_a = ui.select(options={}, label="Импорт A").props("dense outlined").classes("flex-1")
                imp_b = ui.select(options={}, label="Импорт B").props("dense outlined").classes("flex-1")
                ui.button("СРАВНИТЬ МОДЕЛИ", on_click=lambda: asyncio.create_task(_cad_diff())).props("dense no-caps")
            cad_summary = ui.label("").style("font-size:.72rem;")

            ui.separator().style("margin:8px 0;")
            ui.label("Текстовый дифф (вставь две ревизии):").style("font-size:.65rem;color:var(--dim);")
            with ui.row().classes("w-full gap-2"):
                txt_a = ui.textarea(placeholder="Ревизия A").props("dense outlined").classes("flex-1").style("font-size:.72rem;")
                txt_b = ui.textarea(placeholder="Ревизия B").props("dense outlined").classes("flex-1").style("font-size:.72rem;")
            ui.button("СРАВНИТЬ ТЕКСТ", on_click=lambda: asyncio.create_task(_text_diff())).props("dense no-caps")
            diff_out = ui.html("").style("font-size:.72rem;font-family:var(--font);")

            async def _cad_diff():
                if not imp_a.value or not imp_b.value:
                    ui.notify("Выбери два импорта", type="warning")
                    return
                if imp_a.value == imp_b.value:
                    ui.notify("Импорты совпадают", type="warning")
                    return
                d = await api_get(f"/api/diff/cad-bim?import_a={imp_a.value}&import_b={imp_b.value}")
                if not d:
                    ui.notify(last_api_error_text("Дифф не выполнен"), type="negative")
                    return
                cad_summary.text = (
                    f"+ добавлено {d.get('added_count',0)} · − удалено {d.get('removed_count',0)} · "
                    f"~ изменено {d.get('changed_count',0)} · = без изменений {d.get('unchanged_count',0)}"
                )

            async def _text_diff():
                if not (txt_a.value or "").strip() or not (txt_b.value or "").strip():
                    ui.notify("Заполни оба поля", type="warning")
                    return
                d = await api_post("/api/diff/text", {"text_a": txt_a.value, "text_b": txt_b.value})
                if not d:
                    ui.notify(last_api_error_text("Дифф не выполнен"), type="negative")
                    return
                changes = d.get("changed", [])
                added, removed = d.get("added", []), d.get("removed", [])
                import html as _h
                out = [
                    f"<b>Изменено:</b> {d.get('changed_count', len(changes))} · "
                    f"<b>добавлено:</b> {d.get('added_count', len(added))} · "
                    f"<b>удалено:</b> {d.get('removed_count', len(removed))}<br>"
                ]
                for c in changes[:30]:
                    snippet = _h.escape(c.get("diff", "")).replace("\n", "<br>")
                    out.append(
                        f"<div style='margin-top:6px'><span style='color:#d6a400'>~ п.{_h.escape(c.get('clause',''))}</span> "
                        f"(сходство {c.get('similarity','?')})<br>"
                        f"<code style='color:var(--dim)'>{snippet}</code></div>"
                    )
                for a in added[:15]:
                    out.append(f"<div style='color:var(--ok)'>+ п.{_h.escape(a.get('clause',''))}</div>")
                for r in removed[:15]:
                    out.append(f"<div style='color:var(--err)'>− п.{_h.escape(r.get('clause',''))}</div>")
                diff_out.content = "".join(out)

        async def _refresh():
            ds_list = await _datasets()
            opts = _ds_options(ds_list)
            bor_ds.options = opts
            nc_ds.options = opts
            bor_ds.update()
            nc_ds.update()
            imports = (await api_get("/api/diff/cad-bim/imports") or {}).get("imports", [])
            imp_opts = {
                i["id"]: f"{i.get('source','?')} · {i.get('element_count',0)}эл · {str(i.get('created_at',''))[:16]}"
                for i in imports
            }
            imp_a.options = imp_opts
            imp_b.options = imp_opts
            imp_a.update()
            imp_b.update()

        asyncio.create_task(_refresh())
