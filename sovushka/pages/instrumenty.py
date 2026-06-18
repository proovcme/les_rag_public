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

        # ───────────────────── ПЛАН/ФАКТ (W11.2) ─────────────────────
        with ui.card().classes("card-les w-full"):
            ui.label("ПЛАН/ФАКТ — ВОР ↔ ЖУРНАЛ ПОЛЕВЫХ ОБЪЁМОВ").classes("section-title")
            with ui.row().classes("w-full gap-2 items-center"):
                pf_ds = ui.select(options={}, label="Датасет со спецификациями (план)").props(
                    "dense outlined"
                ).classes("flex-1")
                pf_zah = ui.input(label="Захватка (необяз.)").props("dense outlined").style("max-width:170px;")
                ui.button("СФОРМИРОВАТЬ", on_click=lambda: asyncio.create_task(_pf_generate())).props("dense no-caps")
                ui.button("СКАЧАТЬ XLSX", on_click=lambda: asyncio.create_task(
                    _download(f"/api/bor/{pf_ds.value}/plan-fact/download")
                )).props("dense flat no-caps")
            pf_summary = ui.label("План — из ВОР (спецификации), факт — confirmed-записи журнала ОБЪЁМЫ. Числа: SQL/Parquet, 0 LLM.").style(
                "font-size:.7rem;color:var(--dim);"
            )
            pf_tbl = ui.table(
                columns=[
                    {"name": "name", "label": "Наименование", "field": "name", "align": "left"},
                    {"name": "unit", "label": "Ед.", "field": "unit", "align": "center"},
                    {"name": "plan_qty", "label": "План", "field": "plan_qty", "align": "right"},
                    {"name": "fact_qty", "label": "Факт", "field": "fact_qty", "align": "right"},
                    {"name": "remaining", "label": "Остаток", "field": "remaining", "align": "right"},
                    {"name": "done_pct", "label": "Готово,%", "field": "done_pct", "align": "right"},
                    {"name": "status", "label": "Статус", "field": "status", "align": "center"},
                ],
                rows=[], row_key="name",
            ).classes("w-full").style("font-size:.72rem;")
            pf_tbl.add_slot("body-cell-status", """
                <q-td :props="props">
                  <span :style="{fontWeight:'800', color:
                    props.value==='over' ? '#ef4444' :
                    props.value==='matched' ? '#10b981' :
                    props.value==='plan_only' ? '#f59e0b' : '#38bdf8'}">
                    {{ {over:'перевыполн.', matched:'в работе', plan_only:'не начато', fact_only:'вне плана'}[props.value] || props.value }}
                  </span>
                </q-td>""")

            async def _pf_generate():
                if not pf_ds.value:
                    ui.notify("Выбери датасет", type="warning")
                    return
                add_log(f"[ПЛАН/ФАКТ] generate {pf_ds.value}")
                zah = (pf_zah.value or "").strip()
                zq = f"?zahvatka={zah}" if zah else ""
                d = await api_post(f"/api/bor/{pf_ds.value}/plan-fact/generate{zq}")
                if not d:
                    ui.notify(last_api_error_text("План/факт: нет данных (нужны ВОР и журнал)"), type="negative")
                    return
                t = d.get("totals", {})
                pf_summary.text = (
                    f"Строк: {t.get('lines',0)} · в работе {t.get('matched',0)} · "
                    f"перевыполн. {t.get('over',0)} · не начато {t.get('plan_only',0)} · "
                    f"вне плана {t.get('fact_only',0)}"
                )
                prev = await api_get(
                    f"/api/bor/{pf_ds.value}/plan-fact?limit=300" + (f"&zahvatka={zah}" if zah else "")
                ) or {}
                pf_tbl.rows = prev.get("rows", [])
                pf_tbl.update()
                ui.notify(pf_summary.text, type="positive")

        # ──────────────── СВЕРКА ВОР↔КС-2↔СМЕТА↔ИД (W11.4) ────────────────
        with ui.card().classes("card-les w-full"):
            ui.label("СВЕРКА КОЛИЧЕСТВ МЕЖДУ ДОКУМЕНТАМИ (ВОР ↔ КС-2 ↔ СМЕТА ↔ ИД)").classes("section-title")
            ui.label(
                "Выбери датасеты с табличными документами — типы (смета/КС-2/спецификация/ИД) "
                "группируются автоматически. Количества по позициям сравниваются: расхождения и пробелы "
                "помечаются. Числа — Parquet, 0 LLM."
            ).style("font-size:.66rem;color:var(--dim);")
            with ui.row().classes("w-full gap-2 items-center"):
                rec_ds = ui.select(options={}, label="Датасеты для сверки", multiple=True).props(
                    "dense outlined use-chips"
                ).classes("flex-1")
                ui.button("СВЕРИТЬ", on_click=lambda: asyncio.create_task(_rec_run())).props("dense no-caps")
                ui.button("СКАЧАТЬ XLSX", on_click=lambda: asyncio.create_task(_rec_download())).props(
                    "dense flat no-caps"
                )
            rec_summary = ui.label("").style("font-size:.7rem;color:var(--dim);")
            rec_tbl = ui.table(columns=[], rows=[], row_key="name").classes("w-full").style("font-size:.72rem;")
            rec_tbl.add_slot("body-cell-status", """
                <q-td :props="props">
                  <span :style="{fontWeight:'800', color:
                    props.value==='mismatch' ? '#ef4444' :
                    props.value==='gap' ? '#f59e0b' :
                    props.value==='match' ? '#10b981' : '#94a3b8'}">
                    {{ {mismatch:'РАСХОЖДЕНИЕ', gap:'пробел', match:'сходится', single:'один док.'}[props.value] || props.value }}
                  </span>
                </q-td>""")

            def _rec_apply(result: dict):
                doc_types = result.get("doc_types", [])
                labels = result.get("doc_type_labels", {})
                cols = [
                    {"name": "name", "label": "Наименование", "field": "name", "align": "left"},
                    {"name": "unit", "label": "Ед.", "field": "unit", "align": "center"},
                ]
                cols += [{"name": f"src_{dt}", "label": labels.get(dt, dt), "field": f"src_{dt}",
                          "align": "right"} for dt in doc_types]
                cols += [
                    {"name": "delta_pct", "label": "Δ %", "field": "delta_pct", "align": "right"},
                    {"name": "status", "label": "Статус", "field": "status", "align": "center"},
                ]
                rows = []
                for r in result.get("rows", []):
                    row = {"name": r["name"], "unit": r["unit"],
                           "delta_pct": r["delta_pct"] if r["delta_pct"] is not None else "—",
                           "status": r["status"]}
                    for dt in doc_types:
                        v = r["qty_by_source"].get(dt)
                        row[f"src_{dt}"] = v if v is not None else ("—" if dt in r["present"] else "·")
                    rows.append(row)
                rec_tbl.columns = cols
                rec_tbl.rows = rows
                rec_tbl.update()

            async def _rec_run():
                ids = rec_ds.value or []
                if len(ids) < 1:
                    ui.notify("Выбери хотя бы один датасет", type="warning")
                    return
                add_log(f"[СВЕРКА] {','.join(ids)}")
                d = await api_get(f"/api/bor/reconcile?datasets={','.join(ids)}&limit=400")
                if not isinstance(d, dict):
                    ui.notify(last_api_error_text("Сверка: нет табличных позиций"), type="negative")
                    return
                t = d.get("totals", {})
                rec_summary.text = (
                    f"Позиций: {t.get('lines',0)} · РАСХОЖДЕНИЙ {t.get('mismatch',0)} · "
                    f"пробелов {t.get('gap',0)} · сходится {t.get('match',0)} · "
                    f"один док. {t.get('single',0)}"
                )
                _rec_apply(d)
                ui.notify(rec_summary.text, type="positive" if not t.get("mismatch") else "warning")

            async def _rec_download():
                ids = rec_ds.value or []
                if len(ids) < 1:
                    ui.notify("Выбери датасеты", type="warning")
                    return
                gen = await api_post(f"/api/bor/reconcile/generate?datasets={','.join(ids)}")
                if not gen:
                    ui.notify(last_api_error_text("Сверка: нечего выгружать"), type="negative")
                    return
                await _download("/api/bor/reconcile/download")

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

        # ──────────────────── ФОРМЫ ДОКУМЕНТОВ (W11.3/W19) ────────────────────
        with ui.card().classes("card-les w-full"):
            ui.label("ФОРМЫ ДОКУМЕНТОВ — ЗАПОЛНЕНИЕ ИЗ ОБЪЕКТА (0 LLM)").classes("section-title")
            ui.label(
                "Дескриптор формы + данные объекта (W17) → документ. Числа/значения — детерминированно; "
                "ИИ при заполнении не участвует. docx — с фирменным образцом или без него."
            ).style("font-size:.66rem;color:var(--dim);")
            with ui.row().classes("w-full gap-2 items-center"):
                fm_form = ui.select(options={}, label="Форма").props("dense outlined").classes("flex-1")
                fm_proj = ui.select(options={}, label="Объект").props("dense outlined").classes("flex-1")
                fm_fmt = ui.select(options={"docx": "docx", "xlsx": "xlsx", "html": "html (превью)"},
                                   value="docx", label="Формат").props("dense outlined").style("max-width:150px;")
                ui.button("ПОЛЯ", on_click=lambda: asyncio.create_task(_fm_fields())).props("dense flat no-caps")
                ui.button("СГЕНЕРИРОВАТЬ", on_click=lambda: asyncio.create_task(_fm_generate())).props("dense no-caps")
            fm_legal = ui.label("").style("font-size:.64rem;color:var(--dim);")
            fm_inputs_box = ui.column().classes("w-full gap-1")
            fm_preview = ui.html("").style("font-size:.74rem;font-family:var(--font);")
            fm_state: dict = {"inputs": {}}

            async def _fm_fields():
                if not fm_form.value:
                    ui.notify("Выбери форму", type="warning")
                    return
                pid = fm_proj.value
                pq = f"?project_id={pid}" if pid else ""
                d = await api_get(f"/api/forms/{fm_form.value}/fields{pq}")
                if not isinstance(d, dict):
                    ui.notify(last_api_error_text("Поля не загружены"), type="negative")
                    return
                fm_legal.text = d.get("legal_basis", "")
                fm_inputs_box.clear()
                fm_state["inputs"] = {}
                with fm_inputs_box:
                    for f in d.get("fields", []):
                        if f.get("source") == "manual":
                            inp = ui.input(label=f["label"], value=f.get("value", "")).props(
                                "dense outlined"
                            ).classes("w-full")
                            if f.get("needs_input"):
                                inp.props('bg-color="amber-1"')
                            fm_state["inputs"][f["key"]] = inp
                        else:
                            ui.label(f"• {f['label']}: {f.get('value') or '—'}  "
                                     f"[{f.get('source')}]").style("font-size:.7rem;")

            async def _fm_generate():
                if not fm_form.value:
                    ui.notify("Выбери форму", type="warning")
                    return
                manual = {k: (inp.value or "") for k, inp in fm_state["inputs"].items()}
                body = {"project_id": fm_proj.value or None, "fmt": fm_fmt.value, "manual": manual}
                add_log(f"[ФОРМЫ] generate {fm_form.value} → {fm_fmt.value}")
                d = await api_post(f"/api/forms/{fm_form.value}/generate", body)
                if not isinstance(d, dict):
                    ui.notify(last_api_error_text("Генерация не удалась"), type="negative")
                    return
                if d.get("html"):
                    fm_preview.content = d["html"]
                    ui.notify("Превью готово", type="positive")
                elif d.get("download"):
                    fm_preview.content = ""
                    await _download(d["download"])
                    ui.notify("Документ сгенерирован", type="positive")

        async def _refresh():
            ds_list = await _datasets()
            opts = _ds_options(ds_list)
            bor_ds.options = opts
            nc_ds.options = opts
            pf_ds.options = opts
            rec_ds.options = opts
            bor_ds.update()
            nc_ds.update()
            pf_ds.update()
            rec_ds.update()
            forms = (await api_get("/api/forms") or {}).get("forms", [])
            fm_form.options = {f["id"]: f.get("title", f["id"]) for f in forms}
            fm_form.update()
            projects = (await api_get("/api/projects") or {}).get("projects", [])
            fm_proj.options = {p["id"]: p.get("name", p["id"]) for p in projects}
            fm_proj.update()
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
