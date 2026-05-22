"""
С.О.В.У.Ш.К.А. v5.0 — Вкладка С.А.М.О.В.А.Р. (RAG-индекс)
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from urllib.parse import quote
from nicegui import ui

from sovushka.state import state, api_post, api_delete, add_log, refresh_samovar, last_api_error_text


def build_samovar():
    """Строит содержимое вкладки С.А.М.О.В.А.Р. Вызывать внутри with ui.tab_panel(tab_samovar)."""
    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
        with ui.row().classes("items-center justify-between w-full"):
            with ui.column().classes("gap-0"):
                ui.label("С.А.М.О.В.А.Р. // ИНДЕКС ЗНАНИЙ").style(
                    "font-size:1rem;font-weight:900;letter-spacing:1px;"
                )
                ui.label("/api/rag/sources + /api/rag/datasets").style(
                    "font-size:.6rem;color:var(--dim);"
                )
            ui.button(
                "↻ ОБНОВИТЬ",
                on_click=lambda: asyncio.create_task(refresh_and_render())
            ).props("no-caps outline").style(
                "border-color:var(--accent);color:var(--accent);font-size:.7rem;"
            )

        # KPI строка
        with ui.row().classes("w-full gap-3"):
            sam_kpi = {}
            for key, lbl, color in [
                ("ds",     "Датасетов",       "var(--text)"),
                ("src",    "Файлов в папках",  "var(--text)"),
                ("idx",    "В индексе",        "var(--ok)"),
                ("pend",   "Ожидают",          "var(--warn)"),
                ("chunks", "Чанков Qdrant",    "var(--text)"),
            ]:
                with ui.card().classes("kpi-box flex-1"):
                    v = ui.label("—").classes("kpi-val").style(
                        f"color:{color};font-size:1.6rem;font-weight:900;"
                    )
                    ui.label(lbl).classes("kpi-lbl").style(
                        "font-size:.62rem;text-transform:uppercase;color:var(--dim);margin-top:4px;"
                    )
                    sam_kpi[key] = v

        # Таблица датасетов
        sam_tbl_cols = [
            {"name": "folder",   "label": "Папка",    "field": "folder",   "align": "left",   "sortable": True},
            {"name": "total",    "label": "Файлов",   "field": "total",    "align": "center", "sortable": True},
            {"name": "indexed",  "label": "В индексе", "field": "indexed",  "align": "center", "sortable": True},
            {"name": "pending",  "label": "Ожидают",  "field": "pending",  "align": "center", "sortable": True},
            {"name": "chunks",   "label": "Чанков",   "field": "chunks",   "align": "center", "sortable": True},
            {"name": "status",   "label": "Статус",   "field": "status",   "align": "left"},
            {"name": "job_info", "label": "Job",      "field": "job_info", "align": "left"},
            {"name": "actions",  "label": "",          "field": "folder",   "align": "center"},
        ]
        sam_grid = ui.table(
            columns=sam_tbl_cols, rows=[], row_key="folder"
        ).classes("w-full").style(
            "background:var(--bg-panel);color:var(--text);font-family:var(--font);"
        )
        sam_grid.add_slot("body-cell-indexed", """
            <q-td :props="props">
              <span :style="{color: props.value > 0 ? '#10b981' : '#94a3b8', fontWeight:'700'}">{{ props.value }}</span>
            </q-td>""")
        sam_grid.add_slot("body-cell-pending", """
            <q-td :props="props">
              <span :style="{color: props.value > 0 ? '#f59e0b' : '#94a3b8', fontWeight:'700'}">{{ props.value }}</span>
            </q-td>""")
        sam_grid.add_slot("body-cell-status", """
            <q-td :props="props">
              <span :style="{color: ['INDEXED','READY'].includes(props.value)?'#10b981':['PARSING','SCANNING'].includes(props.value)?'#f59e0b':'#94a3b8'}">
                {{ props.value }}
              </span>
            </q-td>""")
        sam_grid.add_slot("body-cell-actions", """
            <q-td :props="props" auto-width>
              <q-btn flat dense size="xs" color="primary" icon="sync"
                     @click="$parent.$emit('sync', props.row)"
                     style="font-size:.6rem;padding:2px 6px;">SYNC</q-btn>
              <q-btn flat dense size="xs" color="negative" icon="delete_sweep"
                     @click="$parent.$emit('reset', props.row)"
                     style="font-size:.6rem;padding:2px 6px;margin-left:4px;">↺ СБРОС</q-btn>
            </q-td>""")
        sam_grid.on("sync",  lambda e: asyncio.create_task(_sync_row(e.args)))
        sam_grid.on("reset", lambda e: asyncio.create_task(_reset_row(e.args)))

        # Поле ручного синка
        with ui.row().classes("gap-3 w-full"):
            sync_folder_input = ui.input(
                placeholder="Имя папки для синка..."
            ).style(
                "background:var(--bg);border:1px solid var(--border);color:var(--text);"
                "font-family:var(--font);border-radius:4px;padding:6px 10px;font-size:.75rem;flex:1;"
            ).classes("flex-1")

            async def do_sync():
                folder = sync_folder_input.value.strip()
                if not folder:
                    ui.notify("Укажи имя папки", type="warning")
                    return
                add_log(f"[SYNC] Запуск: {folder}")
                d = await api_post(f"/api/rag/sync/{quote(folder, safe='')}")
                if d:
                    ui.notify(
                        f"SYNC запущен. Job: {d.get('job_id','?')} | +{d.get('new_files',0)} новых",
                        type="positive"
                    )
                    add_log(f"[SYNC] {folder} → job {d.get('job_id')} +{d.get('new_files',0)} новых")
                    await asyncio.sleep(3)
                    await refresh_and_render()
                else:
                    ui.notify(last_api_error_text(f"Ошибка SYNC {folder}"), type="negative")

            ui.button("↻ SYNC", on_click=do_sync).props("no-caps outline").style(
                "border-color:var(--accent);color:var(--accent);font-size:.7rem;"
            )

        # История Jobs
        with ui.card().classes("card-les w-full"):
            ui.label("ИСТОРИЯ JOBS").classes("section-title mb-3")
            jobs_tbl_cols = [
                {"name": "job_id",   "label": "Job",       "field": "job_id",   "align": "left"},
                {"name": "dataset",  "label": "Датасет",   "field": "dataset",  "align": "left",   "sortable": True},
                {"name": "status",   "label": "Статус",    "field": "status",   "align": "left",   "sortable": True},
                {"name": "progress", "label": "Файлов",    "field": "progress", "align": "center"},
                {"name": "started",  "label": "Начало",    "field": "started",  "align": "left",   "sortable": True},
                {"name": "message",  "label": "Сообщение", "field": "message",  "align": "left"},
            ]
            jobs_grid = ui.table(
                columns=jobs_tbl_cols, rows=[], row_key="job_id"
            ).classes("w-full").style(
                "background:var(--bg-panel);color:var(--text);font-family:var(--font);"
            )

        # ── Внутренние функции ──

        async def _sync_row(row):
            folder = row.get("folder", "") if isinstance(row, dict) else str(row)
            if not folder:
                return
            add_log(f"[SYNC] Запуск: {folder}")
            d = await api_post(f"/api/rag/sync/{quote(folder, safe='')}")
            if d:
                ui.notify(
                    f"✓ SYNC {folder}: job {d.get('job_id','?')} +{d.get('new_files',0)} файлов",
                    type="positive"
                )
                add_log(f"[SYNC] {folder} → job {d.get('job_id')} +{d.get('new_files',0)} новых")
                await asyncio.sleep(2)
                await refresh_and_render()
            else:
                ui.notify(last_api_error_text(f"Ошибка SYNC {folder}"), type="negative")

        async def _reset_row(row):
            folder    = row.get("folder", "") if isinstance(row, dict) else str(row)
            ds_id     = row.get("dataset_id", "") if isinstance(row, dict) else ""
            if not folder:
                return
            ok = await ui.run_javascript(f"confirm('Удалить индекс {folder} и запустить переиндексацию?')")
            if not ok:
                return
            add_log(f"[СБРОС] {folder}: удаление датасета {ds_id}")
            if ds_id:
                d_del = await api_delete(f"/api/rag/datasets/{quote(ds_id, safe='')}")
                if not d_del:
                    ui.notify(last_api_error_text(f"Ошибка удаления датасета {folder}"), type="negative")
                    return
            ui.notify(f"↺ Датасет {folder} удалён — запускаю полную переиндексацию", type="warning")
            await asyncio.sleep(0.5)
            d = await api_post(f"/api/rag/sync/{quote(folder, safe='')}")
            if d:
                add_log(f"[СБРОС] {folder} → job {d.get('job_id')} переиндексация")
                ui.notify(f"✓ Переиндексация запущена: job {d.get('job_id','?')}", type="positive")
                await asyncio.sleep(2)
                await refresh_and_render()
            else:
                ui.notify(last_api_error_text(f"Ошибка sync после сброса {folder}"), type="negative")

        async def refresh_and_render():
            await refresh_samovar()
            _render()

        def _render():
            sources  = state.get("sources", [])
            datasets = state.get("datasets", [])
            jobs     = state.get("jobs", {})
            ds_map   = {d["id"]: d for d in datasets}

            tot_src = tot_idx = tot_chunks = 0
            rows = []
            for src in sources:
                total   = src.get("source_files", 0)
                indexed = src.get("indexed_files", 0)
                pending = max(0, total - indexed)
                ds      = ds_map.get(src.get("dataset_id", "")) or {}
                chunks  = ds.get("chunk_count", 0) or 0
                status  = src.get("dataset_status", "NOT_CREATED")
                tot_src    += total
                tot_idx    += indexed
                tot_chunks += chunks

                folder_jobs = [
                    j for j in jobs.values()
                    if j.get("dataset_name") == f"{src['folder']}_Index"
                ]
                last_job = None
                if folder_jobs:
                    last_job = sorted(
                        folder_jobs,
                        key=lambda j: j.get("started_at", ""),
                        reverse=True
                    )[0]

                job_info = ""
                if last_job:
                    job_info = (
                        f"{last_job['status']} "
                        f"{last_job.get('processed',0)}/{last_job.get('total',0)}"
                    )

                rows.append({
                    "folder":     src.get("folder", ""),
                    "dataset_id": src.get("dataset_id", ""),
                    "total":      total,
                    "indexed":    indexed,
                    "pending":    pending,
                    "chunks":     chunks,
                    "status":     status,
                    "job_info":   job_info,
                })

            sam_kpi["ds"].set_text(str(len(sources)))
            sam_kpi["src"].set_text(str(tot_src))
            sam_kpi["idx"].set_text(str(tot_idx))
            sam_kpi["pend"].set_text(str(max(0, tot_src - tot_idx)))
            sam_kpi["chunks"].set_text(str(tot_chunks))
            sam_grid.rows = rows
            sam_grid.update()

            # Jobs
            job_rows = []
            for jid, j in jobs.items():
                dt_str = ""
                if j.get("started_at"):
                    try:
                        dt = datetime.fromisoformat(j["started_at"].replace("Z", ""))
                        dt_str = dt.strftime("%d.%m %H:%M")
                    except Exception:
                        dt_str = j["started_at"]
                job_rows.append({
                    "job_id":   jid[:12],
                    "dataset":  j.get("dataset_name", ""),
                    "status":   j.get("status", ""),
                    "progress": f"{j.get('processed',0)}/{j.get('total',0)}",
                    "started":  dt_str,
                    "message":  j.get("message", ""),
                })
            job_rows.sort(key=lambda r: r["started"], reverse=True)
            jobs_grid.rows = job_rows
            jobs_grid.update()

        # Загружаем при входе
        ui.timer(0.3, lambda: asyncio.create_task(refresh_and_render()), once=True)
