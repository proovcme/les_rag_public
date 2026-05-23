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
                ("err",    "Ошибок",           "var(--err)"),
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
            {"name": "errors",   "label": "Ошибки",   "field": "errors",   "align": "center", "sortable": True},
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
        sam_grid.add_slot("body-cell-errors", """
            <q-td :props="props">
              <span :style="{color: props.value > 0 ? '#ef4444' : '#94a3b8', fontWeight:'700'}">{{ props.value }}</span>
            </q-td>""")
        sam_grid.add_slot("body-cell-status", """
            <q-td :props="props">
              <span :style="{color: ['INDEXED','READY'].includes(props.value)?'#10b981':['PARSING','SCANNING'].includes(props.value)?'#f59e0b':'#94a3b8'}">
                {{ props.value }}
              </span>
            </q-td>""")
        sam_grid.add_slot("body-cell-actions", """
            <q-td :props="props" auto-width>
              <q-btn v-if="props.row.can_sync" flat dense size="xs" color="primary" icon="sync"
                     @click="$parent.$emit('sync', props.row)"
                     style="font-size:.6rem;padding:2px 6px;">SYNC</q-btn>
              <q-btn v-if="props.row.can_sync" flat dense size="xs" color="negative" icon="delete_sweep"
                     @click="$parent.$emit('reset', props.row)"
                     style="font-size:.6rem;padding:2px 6px;margin-left:4px;">↺ СБРОС</q-btn>
              <span v-if="!props.row.can_sync" style="color:#94a3b8;font-size:.65rem;">—</span>
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

        # Parse scheduler
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between w-full gap-3"):
                with ui.column().classes("gap-0"):
                    ui.label("INDEXING MODE // PARSE SCHEDULER").classes("section-title")
                    scheduler_status = ui.label("pending: — · job: —").style(
                        "font-size:.65rem;color:var(--dim);"
                    )
                with ui.row().classes("items-center gap-2"):
                    batch_limit_input = ui.number("batch", value=1, min=1, max=25, step=1).props("dense outlined").style(
                        "width:86px;font-size:.7rem;"
                    )
                    max_batches_input = ui.number("max", value=25, min=1, max=500, step=1).props("dense outlined").style(
                        "width:86px;font-size:.7rem;"
                    )
                    cooldown_input = ui.number("cooldown", value=20, min=0, max=600, step=5).props("dense outlined").style(
                        "width:112px;font-size:.7rem;"
                    )
                    min_free_input = ui.number("min GB", value=8, min=1, max=64, step=1).props("dense outlined").style(
                        "width:92px;font-size:.7rem;"
                    )
                    max_swap_input = ui.number("swap %", value=45, min=0, max=100, step=5).props("dense outlined").style(
                        "width:92px;font-size:.7rem;"
                    )

                    async def run_scheduler():
                        payload = {
                            "batch_limit": int(batch_limit_input.value or 5),
                            "max_batches": int(max_batches_input.value or 25),
                            "cooldown_sec": float(cooldown_input.value or 0),
                            "unload_between_batches": True,
                            "unload_before_start": True,
                            "min_free_gb": float(min_free_input.value or 8),
                            "max_swap_pct": float(max_swap_input.value or 45),
                            "background": True,
                        }
                        add_log(
                            f"[PARSE_SCHEDULER] batch={payload['batch_limit']} "
                            f"max={payload['max_batches']} cooldown={payload['cooldown_sec']}"
                        )
                        start_scheduler_btn.props("loading")
                        d = await api_post("/api/rag/parse-scheduler", payload)
                        start_scheduler_btn.props(remove="loading")
                        if d:
                            ui.notify(f"Scheduler запущен: job {d.get('job_id','?')}", type="positive")
                            add_log(f"[PARSE_SCHEDULER] job {d.get('job_id')} queued")
                            await asyncio.sleep(1)
                            await refresh_and_render()
                        else:
                            ui.notify(last_api_error_text("Ошибка запуска scheduler"), type="negative")

                    start_scheduler_btn = ui.button(
                        "▶ START",
                        on_click=run_scheduler,
                    ).props("no-caps").style(
                        "background:rgba(245,158,11,.15);border:1px solid var(--warn);"
                        "color:var(--warn);font-size:.7rem;font-weight:900;"
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

        # Статус документов
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("ФАЙЛЫ ИНДЕКСАЦИИ").classes("section-title mb-3")
                docs_status = ui.label("INDEXED/PENDING/ERROR").style(
                    "font-size:.65rem;color:var(--dim);"
                )
            docs_tbl_cols = [
                {"name": "status", "label": "Статус", "field": "status", "align": "left", "sortable": True},
                {"name": "dataset", "label": "Датасет", "field": "dataset", "align": "left", "sortable": True},
                {"name": "chunks", "label": "Чанков", "field": "chunks", "align": "center", "sortable": True},
                {"name": "size", "label": "Размер", "field": "size", "align": "right", "sortable": True},
                {"name": "file", "label": "Файл", "field": "file", "align": "left", "sortable": True},
                {"name": "pipeline", "label": "Pipeline", "field": "pipeline", "align": "left"},
            ]
            docs_grid = ui.table(
                columns=docs_tbl_cols, rows=[], row_key="id", pagination=15
            ).classes("w-full").style(
                "background:var(--bg-panel);color:var(--text);font-family:var(--font);"
            )
            docs_grid.add_slot("body-cell-status", """
                <q-td :props="props">
                  <span :style="{color: props.value === 'INDEXED' ? '#10b981' : props.value === 'ERROR' ? '#ef4444' : '#f59e0b', fontWeight:'800'}">
                    {{ props.value }}
                  </span>
                </q-td>""")

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
            rag      = state.get("rag_health", {}) if isinstance(state.get("rag_health"), dict) else {}
            datasets = rag.get("datasets") or state.get("datasets", [])
            totals   = rag.get("totals") or {}
            jobs     = state.get("jobs", {})
            docs     = state.get("rag_documents", {}) if isinstance(state.get("rag_documents"), dict) else {}
            ds_map   = {d["id"]: d for d in datasets}

            tot_src = tot_idx = tot_pending = tot_errors = tot_chunks = 0
            rows = []
            seen_ds = set()
            for src in sources:
                ds      = ds_map.get(src.get("dataset_id", "")) or {}
                total   = ds.get("files", src.get("source_files", 0))
                indexed = ds.get("indexed_files", src.get("indexed_files", 0))
                pending = ds.get("pending_files", max(0, total - indexed))
                errors  = ds.get("error_files", 0)
                chunks  = ds.get("chunks", ds.get("chunk_count", 0) or 0)
                status  = ds.get("status", src.get("dataset_status", "NOT_CREATED"))
                tot_src    += total
                tot_idx    += indexed
                tot_pending += pending
                tot_errors  += errors
                tot_chunks += chunks
                if src.get("dataset_id"):
                    seen_ds.add(src.get("dataset_id"))

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
                    "errors":     errors,
                    "chunks":     chunks,
                    "status":     status,
                    "job_info":   job_info,
                    "can_sync":    True,
                })

            for ds in datasets:
                ds_id = ds.get("id", "")
                if not ds_id or ds_id in seen_ds:
                    continue
                total = ds.get("files", ds.get("doc_count", 0) or 0)
                indexed = ds.get("indexed_files", ds.get("doc_count", 0) or 0)
                pending = ds.get("pending_files", 0)
                errors = ds.get("error_files", 0)
                chunks = ds.get("chunks", ds.get("chunk_count", 0) or 0)
                tot_src += total
                tot_idx += indexed
                tot_pending += pending
                tot_errors += errors
                tot_chunks += chunks
                rows.append({
                    "folder":     ds.get("name", ds_id),
                    "dataset_id": ds_id,
                    "total":      total,
                    "indexed":    indexed,
                    "pending":    pending,
                    "errors":     errors,
                    "chunks":     chunks,
                    "status":     ds.get("status", ""),
                    "job_info":   "",
                    "can_sync":    False,
                })

            if totals:
                tot_src = totals.get("files", tot_src)
                tot_idx = totals.get("indexed_files", tot_idx)
                tot_pending = totals.get("pending_files", tot_pending)
                tot_errors = totals.get("error_files", tot_errors)
                tot_chunks = totals.get("chunks", tot_chunks)

            sam_kpi["ds"].set_text(str(totals.get("datasets", len(datasets) or len(sources))))
            sam_kpi["src"].set_text(str(tot_src))
            sam_kpi["idx"].set_text(str(tot_idx))
            sam_kpi["pend"].set_text(str(tot_pending))
            sam_kpi["err"].set_text(str(tot_errors))
            sam_kpi["chunks"].set_text(str(tot_chunks))
            scheduler_jobs = [
                (jid, j) for jid, j in jobs.items()
                if j.get("type") == "rag_parse_scheduler"
            ]
            last_scheduler = sorted(
                scheduler_jobs,
                key=lambda item: item[1].get("started_at", ""),
                reverse=True,
            )[0] if scheduler_jobs else None
            scheduler_status.set_text(
                f"pending: {tot_pending} · errors: {tot_errors} · "
                f"job: {(last_scheduler[0][:12] + ' ' + last_scheduler[1].get('status','')) if last_scheduler else '—'}"
            )
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

            doc_rows = []
            for item in docs.get("documents", []) if isinstance(docs, dict) else []:
                file_size = int(item.get("file_size") or 0)
                if file_size >= 1024 * 1024:
                    size_text = f"{file_size / (1024 * 1024):.1f} MB"
                elif file_size >= 1024:
                    size_text = f"{file_size / 1024:.0f} KB"
                else:
                    size_text = f"{file_size} B"
                doc_rows.append({
                    "id": item.get("id", item.get("file_name", "")),
                    "status": item.get("status", ""),
                    "dataset": item.get("dataset_name", ""),
                    "chunks": item.get("chunk_count", 0),
                    "size": size_text,
                    "file": item.get("file_name", ""),
                    "pipeline": item.get("pipeline", ""),
                })
            summary = docs.get("summary", {}) if isinstance(docs, dict) else {}
            docs_status.set_text(
                " · ".join(
                    f"{key}: {value.get('files', 0)}"
                    for key, value in summary.items()
                ) or "INDEXED/PENDING/ERROR"
            )
            docs_grid.rows = doc_rows
            docs_grid.update()

        # Загружаем при входе без одноразового timer, чтобы обновление не
        # прилетало в уже удалённый slot при быстрой навигации.
        asyncio.create_task(refresh_and_render())
