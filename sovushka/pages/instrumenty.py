"""
С.О.В.У.Ш.К.А. — Вкладка ИНСТРУМЕНТЫ: детерминированные функции по документам в GUI.

ВОР (ведомости объёмов), нормоконтроль, дифф ревизий — всё, что раньше было
только через curl. 0 LLM на бэке (см. сервисы bor/normcontrol/diff).
"""
from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

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
                bor_mode = ui.toggle(
                    {"svod": "Свод позиций", "works": "Работы из спец. (Ф9)"}, value="svod",
                ).props("dense no-caps").tooltip(
                    "Свод: сумма позиций. Работы: каждая позиция → монтажная работа (объём = кол-во)"
                )
                ui.button("СФОРМИРОВАТЬ", on_click=lambda: asyncio.create_task(_bor_generate())).props("dense no-caps")
                ui.button("СКАЧАТЬ XLSX", on_click=lambda: asyncio.create_task(_bor_download())).props(
                    "dense flat no-caps"
                )
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

            def _bor_paths():
                # (generate, preview, download) под выбранный режим
                seg = "from-spec/" if bor_mode.value == "works" else ""
                base = f"/api/bor/{bor_ds.value}"
                preview = f"{base}/from-spec?limit=300" if bor_mode.value == "works" else f"{base}/preview?limit=200"
                return f"{base}/{seg}generate", preview, f"{base}/{seg}download"

            async def _bor_generate():
                if not bor_ds.value:
                    ui.notify("Выбери датасет", type="warning")
                    return
                gen_path, preview_path, _ = _bor_paths()
                add_log(f"[ВОР] generate {bor_ds.value} mode={bor_mode.value}")
                d = await api_post(gen_path)
                if not d:
                    ui.notify(last_api_error_text("ВОР: нет строк спецификаций"), type="negative")
                    return
                tag = "работ" if bor_mode.value == "works" else "строк"
                ui.notify(f"ВОР: {d.get('bor_lines',0)} {tag} из {d.get('source_rows',0)} исходных", type="positive")
                prev = await api_get(preview_path) or {}
                bor_summary.text = (f"{'Работ' if bor_mode.value=='works' else 'Строк ВОР'}: "
                                    f"{prev.get('bor_lines',0)} · исходных позиций: {prev.get('source_rows',0)}")
                bor_tbl.rows = prev.get("lines", [])
                bor_tbl.update()

            async def _bor_download():
                if not bor_ds.value:
                    ui.notify("Выбери датасет", type="warning")
                    return
                await _download(_bor_paths()[2])

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
                "Выбери датасеты с табличными документами (ВОР, акты, ведомости, КС-2, сметы) — "
                "количества по позициям сравниваются между документами: расхождения и пробелы "
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

        # ──────────────── ФГИС ЦС — ЦЕНА ПО КОДУ РЕСУРСА ────────────────
        with ui.card().classes("card-les w-full"):
            ui.label("ФГИС ЦС — СМЕТНАЯ ЦЕНА ПО КОДУ РЕСУРСА (0 LLM)").classes("section-title")
            ui.label(
                "Точный поиск цены/индекса по коду из «Сплит-формы» (текущая = база×индекс или прямая). "
                "Exact-match по коду, не векторный top-k — SQL-замена для автоценообразования ЛСР."
            ).style("font-size:.66rem;color:var(--dim);")
            with ui.row().classes("w-full gap-2 items-center"):
                pr_book = ui.select(options={}, label="Книга цен").props("dense outlined").style("max-width:220px;")
                pr_code = ui.input(label="Код ресурса (91.05.01-017)").props("dense outlined").classes("flex-1")
                pr_method = ui.toggle({"index": "Текущая", "base": "Базовая"}, value="index").props("dense no-caps")
                ui.button("НАЙТИ", on_click=lambda: asyncio.create_task(_pr_lookup())).props("dense no-caps")
            pr_result = ui.html("").style("font-size:.78rem;")
            ui.separator().style("margin:6px 0;")
            with ui.row().classes("w-full gap-2 items-center"):
                pr_q = ui.input(label="Поиск по наименованию (если код неизвестен)").props(
                    "dense outlined"
                ).classes("flex-1")
                ui.button("ИСКАТЬ", on_click=lambda: asyncio.create_task(_pr_search())).props("dense flat no-caps")
            pr_tbl = ui.table(
                columns=[
                    {"name": "code", "label": "Код", "field": "code", "align": "left"},
                    {"name": "name", "label": "Наименование", "field": "name", "align": "left"},
                    {"name": "unit", "label": "Ед.", "field": "unit", "align": "center"},
                    {"name": "price_base", "label": "База", "field": "price_base", "align": "right"},
                    {"name": "index", "label": "Индекс", "field": "index", "align": "right"},
                    {"name": "price_current_eff", "label": "Текущая", "field": "price_current_eff", "align": "right"},
                ],
                rows=[], row_key="code",
            ).classes("w-full").style("font-size:.72rem;")
            ui.separator().style("margin:6px 0;")
            ui.label(
                "ОБНОВИТЬ КНИГУ из ФГИС ЦС (наполнение). Источник цен — ТОЛЬКО файл-выгрузка "
                "(per-code API закрыт). Канал недоверенный: query-time не дёргается, при сбое — graceful."
            ).style("font-size:.62rem;color:var(--dim);")
            with ui.row().classes("w-full gap-2 items-center"):
                pr_subj = ui.input(label="Субъект (Петербург)", value="Петербург").props(
                    "dense outlined").style("max-width:200px;")
                pr_qtr = ui.input(label="Квартал (2 квартал 2025)", value="2 квартал 2025").props(
                    "dense outlined").style("max-width:200px;")
                pr_name = ui.input(label="Имя книги (spb_2kv2025)", value="spb_2kv2025").props(
                    "dense outlined").style("max-width:180px;")
                ui.button("ОБНОВИТЬ", on_click=lambda: asyncio.create_task(_pr_update())).props(
                    "dense flat no-caps")
            pr_upd_result = ui.html("").style("font-size:.72rem;")

            async def _pr_update():
                body = {"subject": pr_subj.value or "Петербург",
                        "quarter": pr_qtr.value or "2 квартал 2025",
                        "name": (pr_name.value or "spb_2kv2025").strip()}
                ui.notify("Качаю «Сплит-форму» из ФГИС ЦС — это файл ≈8 МБ…", type="info")
                d = await api_post("/api/prices/update", body)
                if not isinstance(d, dict) or not d.get("ok"):
                    pr_upd_result.content = (
                        f"<span style='color:var(--err)'>"
                        f"{last_api_error_text('ФГИС ЦС недоступен — книга не тронута')}</span>")
                    return
                pr_upd_result.content = (
                    f"<span style='color:var(--ok)'>Готово</span>: {d['region']} {d['quarter']} · "
                    f"<b>{d['rows']}</b> строк ({d['bytes']//1024} КБ) → {d['name']}")
                books = (await api_get("/api/prices/books") or {}).get("books", [])
                pr_book.options = {b["name"]: b["name"] for b in books}
                pr_book.value = d["name"]
                pr_book.update()

            async def _pr_lookup():
                code = (pr_code.value or "").strip()
                if not code:
                    ui.notify("Введи код ресурса", type="warning")
                    return
                bq = f"&book={quote(pr_book.value)}" if pr_book.value else ""
                d = await api_get(f"/api/prices/lookup?code={quote(code)}&method={pr_method.value}{bq}")
                if not isinstance(d, dict):
                    ui.notify(last_api_error_text("Поиск не выполнен — нет книги цен?"), type="negative")
                    return
                if not d.get("found"):
                    pr_result.content = f"<span style='color:var(--err)'>Код {code} не найден</span>"
                    return
                r = d["row"]
                pr_result.content = (
                    f"<b>{r.get('name','')}</b> · {r.get('unit','')}<br>"
                    f"Цена ({'текущая' if d['method']=='index' else 'базовая'}): "
                    f"<b style='color:var(--ok)'>{d.get('price')}</b> руб. · "
                    f"база {r.get('price_base')} × индекс {r.get('index')} · "
                    f"{d.get('region','')} {d.get('quarter','')}"
                )

            async def _pr_search():
                q = (pr_q.value or "").strip()
                if len(q) < 2:
                    ui.notify("Минимум 2 символа", type="warning")
                    return
                bq = f"&book={quote(pr_book.value)}" if pr_book.value else ""
                d = await api_get(f"/api/prices/search?q={quote(q)}&limit=50{bq}")
                if not isinstance(d, dict):
                    ui.notify(last_api_error_text("Поиск не выполнен"), type="negative")
                    return
                pr_tbl.rows = d.get("rows", [])
                pr_tbl.update()

        # ──────────────── КАЦ — КОНЪЮНКТУРНЫЙ АНАЛИЗ ЦЕН ────────────────
        with ui.card().classes("card-les w-full"):
            ui.label("КАЦ — КОНЪЮНКТУРНЫЙ АНАЛИЗ ЦЕН (0 LLM)").classes("section-title")
            ui.label(
                "Для материалов, которых НЕТ в ФГИС ЦС: ≥3 КП на материал → выбор экономичного → "
                "цена в позицию ЛСР. Котировки правь в таблице (материал · поставщик · цена · источник)."
            ).style("font-size:.66rem;color:var(--dim);")
            with ui.row().classes("w-full gap-2 items-center"):
                kac_min = ui.number(label="Мин. поставщиков", value=3, min=1, max=9).props(
                    "dense outlined"
                ).style("max-width:150px;")
                kac_strat = ui.toggle({"min": "Экономичный", "median": "Медиана"}, value="min").props("dense no-caps")
                ui.button("+ СТРОКА", on_click=lambda: asyncio.create_task(_kac_add())).props("dense flat no-caps")
                ui.button("АНАЛИЗ", on_click=lambda: asyncio.create_task(_kac_run())).props("dense no-caps")
                ui.button("СКАЧАТЬ XLSX", on_click=lambda: asyncio.create_task(_kac_dl())).props("dense flat no-caps")
            kac_grid = ui.aggrid({
                "columnDefs": [
                    {"headerName": "Материал", "field": "material", "editable": True, "minWidth": 200},
                    {"headerName": "Поставщик", "field": "supplier", "editable": True},
                    {"headerName": "Ед.", "field": "unit", "editable": True, "maxWidth": 80},
                    {"headerName": "Цена", "field": "price", "editable": True, "maxWidth": 110},
                    {"headerName": "Источник", "field": "source", "editable": True},
                ],
                "rowData": [
                    {"material": "Гранит серый, плита 600×300×30", "supplier": "ГранитИнвест", "unit": "м2", "price": 2450, "source": "КП ГранитИнвест"},
                    {"material": "Гранит серый, плита 600×300×30", "supplier": "ЛЕВ", "unit": "м2", "price": 2300, "source": "КП ЛЕВ"},
                    {"material": "Гранит серый, плита 600×300×30", "supplier": "ПрофСтрой", "unit": "м2", "price": 2520, "source": "КП ПрофСтрой"},
                ],
                "defaultColDef": {"resizable": True, "sortable": True},
                "singleClickEdit": True,
            }).classes("w-full").style("height:24vh;")
            kac_summary = ui.label("").style("font-size:.7rem;color:var(--dim);")
            kac_tbl = ui.table(
                columns=[
                    {"name": "material", "label": "Материал", "field": "material", "align": "left"},
                    {"name": "unit", "label": "Ед.", "field": "unit", "align": "center"},
                    {"name": "suppliers", "label": "КП", "field": "suppliers", "align": "center"},
                    {"name": "chosen_supplier", "label": "Выбран", "field": "chosen_supplier", "align": "left"},
                    {"name": "chosen_price", "label": "Цена", "field": "chosen_price", "align": "right"},
                    {"name": "spread_pct", "label": "Разброс,%", "field": "spread_pct", "align": "right"},
                    {"name": "sufficient", "label": "≥мин", "field": "sufficient", "align": "center"},
                ],
                rows=[], row_key="material",
            ).classes("w-full").style("font-size:.72rem;")

            def _kac_body(quotes: list) -> dict:
                return {"quotes": quotes, "min_suppliers": int(kac_min.value or 3), "strategy": kac_strat.value}

            async def _kac_add():
                data = await kac_grid.get_client_data()
                data.append({"material": "", "supplier": "", "unit": "", "price": "", "source": ""})
                kac_grid.options["rowData"] = data
                kac_grid.update()

            async def _kac_run():
                quotes = await kac_grid.get_client_data()
                d = await api_post("/api/kac/analyze", _kac_body(quotes))
                if not isinstance(d, dict):
                    ui.notify(last_api_error_text("КАЦ: не посчитан"), type="negative")
                    return
                s = d.get("summary", {})
                kac_summary.text = (
                    f"Материалов: {s.get('materials',0)} · достаточно (≥{int(kac_min.value or 3)} КП): "
                    f"{s.get('sufficient',0)} · недостаточно: {s.get('insufficient',0)} · котировок: {s.get('total_quotes',0)}"
                )
                kac_tbl.rows = [
                    {"material": m["material"], "unit": m["unit"], "suppliers": m["suppliers"],
                     "chosen_supplier": m["chosen_supplier"], "chosen_price": m["chosen_price"],
                     "spread_pct": m["spread_pct"], "sufficient": "✓" if m["sufficient"] else "✗"}
                    for m in d.get("materials", [])
                ]
                kac_tbl.update()

            async def _kac_dl():
                quotes = await kac_grid.get_client_data()
                d = await api_post("/api/kac/generate", _kac_body(quotes))
                if not isinstance(d, dict) or not d.get("download"):
                    ui.notify(last_api_error_text("КАЦ: нечего выгружать"), type="negative")
                    return
                await _download(d["download"])

        # ──────────────── СБОРКА ЛСР (ДВИЖОК) ────────────────
        with ui.card().classes("card-les w-full"):
            ui.label("СБОРКА ЛСР — ОБЪЁМ+РЕСУРСЫ → ЦЕНЫ → СТЕСНЁННОСТЬ → НР/СП → ВСЕГО (0 LLM)").classes("section-title")
            ui.label(
                "Позиции в JSON: объём + ресурсы (kind: labor/machinist/machine/material). Цена строки — явная, "
                "либо ФГИС ЦС по коду (книга), либо КАЦ. Бухгалтерия выверена на эталоне (поз. ниже = 11813.04)."
            ).style("font-size:.66rem;color:var(--dim);")
            with ui.row().classes("w-full gap-2 items-center"):
                la_book = ui.input(label="Книга цен ФГИС ЦС (опц.)").props("dense outlined").style("max-width:210px;")
                la_cond = ui.select(options={}, label="Стеснённость (опц.)").props(
                    "dense outlined clearable"
                ).classes("flex-1")
                ui.button("СОБРАТЬ", on_click=lambda: asyncio.create_task(_la_run())).props("dense no-caps")
            la_json = ui.textarea(value=json.dumps([{
                "code": "ГЭСН12-01-034-02", "name": "Устройство обрешётки", "unit": "100 м2", "qty": 0.61,
                "section": "Раздел 1", "nr_pct": 109, "sp_pct": 57, "resources": [
                    {"kind": "labor", "name": "ОТ(ЗТ)", "qty": 1, "price": 3750.23},
                    {"kind": "machine", "name": "Машины", "qty": 1, "price": 533.72},
                    {"kind": "machinist", "name": "ОТм", "qty": 1, "price": 458.68},
                    {"kind": "material", "name": "Гвозди", "qty": 1, "price": 83.62}]}],
                ensure_ascii=False, indent=1)).props("dense outlined").classes("w-full").style(
                "font-family:monospace;font-size:.68rem;height:18vh;")
            la_out = ui.html("").style("font-size:.8rem;")
            la_tbl = ui.table(columns=[
                {"name": "section", "label": "Раздел", "field": "section", "align": "left"},
                {"name": "positions", "label": "Позиций", "field": "positions", "align": "center"},
                {"name": "total", "label": "Итого, руб.", "field": "total", "align": "right"},
            ], rows=[], row_key="section").classes("w-full").style("font-size:.72rem;")

            async def _la_run():
                try:
                    positions = json.loads(la_json.value or "[]")
                except Exception as e:
                    ui.notify(f"JSON: {e}", type="negative")
                    return
                body: dict = {"positions": positions}
                if la_book.value:
                    body["book"] = la_book.value
                if la_cond.value:
                    body["condition"] = la_cond.value
                d = await api_post("/api/lsr/assemble", body)
                if not isinstance(d, dict):
                    ui.notify(last_api_error_text("ЛСР: не собран"), type="negative")
                    return
                s = d["summary"]
                up = f" (стеснённость +{s['stesnennost_uplift']})" if s.get("stesnennost_uplift") else ""
                warn = f"<br><span style='color:var(--err)'>без цены: {s['needs_price']}</span>" if s.get("needs_price") else ""
                la_out.content = (f"Позиций: {s['positions']} · Итого: "
                                  f"<b style='color:var(--ok)'>{s['total']}</b> руб.{up}{warn}")
                la_tbl.rows = [{"section": x["section"], "positions": x["positions"], "total": x["total"]}
                               for x in d.get("sections", [])]
                la_tbl.update()

        # ──────────────── КОЭФФИЦИЕНТ СТЕСНЁННОСТИ ────────────────
        with ui.card().classes("card-les w-full"):
            ui.label("КОЭФФИЦИЕНТ СТЕСНЁННОСТИ — ПЕРЕСЧЁТ ПОЗИЦИИ ЛСР (0 LLM)").classes("section-title")
            ui.label(
                "Усложняющие условия → коэф. к ОЗП и ЭМ → пересчёт ФОТ/НР/СП/Всего. Материалы не затрагиваются. "
                "Каталог условий редактируется в config/domain/stesnennost.yaml."
            ).style("font-size:.66rem;color:var(--dim);")
            with ui.row().classes("w-full gap-2 items-center"):
                st_cond = ui.select(options={}, label="Условие (или задай k вручную)").props(
                    "dense outlined clearable"
                ).classes("flex-1")
                st_kozp = ui.number(label="k ОЗП", value=None, format="%.2f").props("dense outlined").style("max-width:100px;")
                st_kem = ui.number(label="k ЭМ", value=None, format="%.2f").props("dense outlined").style("max-width:100px;")
            with ui.row().classes("w-full gap-2 items-center flex-wrap"):
                st_ozp = ui.number(label="ОЗП", value=4208.91).props("dense outlined").style("max-width:110px;")
                st_em = ui.number(label="ЭМ", value=533.72).props("dense outlined").style("max-width:110px;")
                st_zpm = ui.number(label="ЗПМ", value=458.68).props("dense outlined").style("max-width:110px;")
                st_mat = ui.number(label="Материалы", value=83.62).props("dense outlined").style("max-width:120px;")
                st_nr = ui.number(label="НР %", value=109).props("dense outlined").style("max-width:90px;")
                st_sp = ui.number(label="СП %", value=57).props("dense outlined").style("max-width:90px;")
                ui.button("РАССЧИТАТЬ", on_click=lambda: asyncio.create_task(_st_run())).props("dense no-caps")
            st_out = ui.html("Позиция-пример — из эталона (медный отлив). Подставь свои числа.").style("font-size:.78rem;color:var(--dim);")

            async def _st_run():
                pos = {"name": "позиция", "ozp": st_ozp.value, "em": st_em.value, "zpm": st_zpm.value,
                       "mat": st_mat.value, "nr_pct": st_nr.value, "sp_pct": st_sp.value}
                body: dict = {"positions": [pos]}
                if st_cond.value:
                    body["condition"] = st_cond.value
                if st_kozp.value:
                    body["k_ozp"] = st_kozp.value
                if st_kem.value:
                    body["k_em"] = st_kem.value
                d = await api_post("/api/lsr/stesnennost/apply", body)
                if not isinstance(d, dict):
                    ui.notify(last_api_error_text("Стеснённость: задай условие или k ОЗП/ЭМ"), type="negative")
                    return
                p = d["positions"][0]
                lbl = f" · {d['condition_label']}" if d.get("condition_label") else ""
                st_out.content = (
                    f"k ОЗП {d['k_ozp']} · k ЭМ {d['k_em']}{lbl}<br>"
                    f"Всего по позиции: <b>{p['base']['total']}</b> → "
                    f"<b style='color:var(--ok)'>{p['adjusted']['total']}</b> руб. (+{p['uplift']})<br>"
                    f"ОЗП {p['base']['ozp']}→{p['adjusted']['ozp']} · ЭМ {p['base']['em']}→{p['adjusted']['em']} · "
                    f"ФОТ {p['base']['fot']}→{p['adjusted']['fot']} · НР {p['base']['nr']}→{p['adjusted']['nr']} · "
                    f"СП {p['base']['sp']}→{p['adjusted']['sp']}"
                )

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
            books = (await api_get("/api/prices/books") or {}).get("books", [])
            pr_book.options = {b["name"]: b["name"] for b in books}
            if books and not pr_book.value:
                pr_book.value = books[0]["name"]
            pr_book.update()
            conds = (await api_get("/api/lsr/stesnennost/conditions") or {}).get("conditions", [])
            cond_opts = {c["id"]: f"{c['label']} (×{c['k_ozp']}/{c['k_em']})" for c in conds}
            st_cond.options = cond_opts
            st_cond.update()
            la_cond.options = cond_opts
            la_cond.update()
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
