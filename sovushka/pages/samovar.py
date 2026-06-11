"""
С.О.В.У.Ш.К.А. v5.0 — Вкладка С.А.М.О.В.А.Р. (RAG-индекс)
"""
from __future__ import annotations

import asyncio
from html import escape
from datetime import datetime
from urllib.parse import quote, urlencode
from nicegui import context, ui

from sovushka.state import (
    state,
    api_get,
    api_post,
    api_delete,
    add_log,
    refresh_proxy_logs,
    refresh_samovar,
    last_api_error_text,
)


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

        runtime_banner = ui.label("runtime: —").classes("w-full").style(
            "border:1px solid var(--border);background:var(--bg-panel);color:var(--dim);"
            "border-radius:6px;padding:8px 10px;font-size:.68rem;font-family:var(--font);"
        )

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
        sam_grid.add_slot("body-cell-folder", """
            <q-td :props="props">
              <q-btn flat dense no-caps align="left" color="primary"
                     @click="$parent.$emit('inspect', props.row)"
                     style="font-family:var(--font-chat);font-size:.72rem;font-weight:800;padding:2px 0;max-width:320px;">
                <span style="display:block;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                  {{ props.value }}
                </span>
              </q-btn>
            </q-td>""")
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
              <span v-if="!props.row.can_sync" :title="props.row.sync_reason"
                    style="color:#94a3b8;font-size:.65rem;cursor:help;border-bottom:1px dotted #94a3b8;">нет синка</span>
            </q-td>""")
        sam_grid.on("inspect", lambda e: asyncio.create_task(_open_index_dialog(e.args)))
        sam_grid.on("sync",  lambda e: asyncio.create_task(_sync_row(e.args)))
        sam_grid.on("reset", lambda e: asyncio.create_task(_reset_row(e.args)))

        selected_index = {"row": {}}
        with ui.dialog() as index_dialog:
            with ui.card().classes("card-les").style(
                "width:min(1180px,96vw);max-width:96vw;max-height:90vh;"
                "background:var(--bg-panel);color:var(--text);"
            ):
                with ui.row().classes("items-center justify-between w-full gap-3"):
                    with ui.column().classes("gap-0"):
                        index_title = ui.label("INDEX // —").style(
                            "font-size:.95rem;font-weight:900;letter-spacing:.6px;"
                        )
                        index_subtitle = ui.label("dataset: —").style(
                            "font-size:.65rem;color:var(--dim);"
                        )
                    ui.button(icon="o_close", on_click=index_dialog.close).props("flat round dense")

                with ui.row().classes("w-full gap-3"):
                    index_kpi = {}
                    for key, label, color in [
                        ("total", "Файлов", "var(--text)"),
                        ("indexed", "INDEXED", "var(--ok)"),
                        ("pending", "PENDING", "var(--warn)"),
                        ("errors", "ERROR", "var(--err)"),
                        ("chunks", "Чанков", "var(--text)"),
                    ]:
                        with ui.card().classes("kpi-box flex-1"):
                            index_kpi[key] = ui.label("—").classes("kpi-val").style(
                                f"color:{color};font-size:1.35rem;font-weight:900;"
                            )
                            ui.label(label).classes("kpi-lbl").style(
                                "font-size:.6rem;text-transform:uppercase;color:var(--dim);margin-top:4px;"
                            )

                with ui.row().classes("items-center gap-2 w-full"):
                    index_status_select = ui.select(
                        {"": "Все статусы", "INDEXED": "INDEXED", "PENDING": "PENDING", "ERROR": "ERROR"},
                        value="",
                        label="status",
                    ).props("dense outlined emit-value map-options").style("width:150px;font-size:.7rem;")
                    index_query_input = ui.input(
                        placeholder="Поиск по имени, домену, ошибке..."
                    ).props("dense outlined clearable").classes("flex-1").style("font-size:.7rem;")
                    index_limit_select = ui.select(
                        [50, 120, 250, 500],
                        value=120,
                        label="limit",
                    ).props("dense outlined").style("width:104px;font-size:.7rem;")
                    ui.button(
                        icon="o_search",
                        on_click=lambda: asyncio.create_task(_refresh_index_dialog_documents()),
                    ).props("flat round dense").tooltip("Искать в этом индексе")
                    ui.button(
                        icon="o_done_all",
                        on_click=lambda: asyncio.create_task(_quick_index_status("INDEXED")),
                    ).props("flat round dense").tooltip("Только INDEXED")
                    ui.button(
                        icon="o_pending_actions",
                        on_click=lambda: asyncio.create_task(_quick_index_status("PENDING")),
                    ).props("flat round dense").tooltip("Только PENDING")
                    ui.button(
                        icon="o_error_outline",
                        on_click=lambda: asyncio.create_task(_quick_index_status("ERROR")),
                    ).props("flat round dense").tooltip("Только ERROR")

                index_docs_status = ui.label("shown: —").style("font-size:.65rem;color:var(--dim);")
                index_docs_cols = [
                    {"name": "status", "label": "Статус", "field": "status", "align": "left", "sortable": True},
                    {"name": "file", "label": "Файл", "field": "file", "align": "left", "sortable": True},
                    {"name": "chunks", "label": "Чанков", "field": "chunks", "align": "center", "sortable": True},
                    {"name": "size", "label": "Размер", "field": "size", "align": "right", "sortable": True},
                    {"name": "domain", "label": "Domain", "field": "domain", "align": "left", "sortable": True},
                    {"name": "doc_type", "label": "Doc", "field": "doc_type", "align": "left", "sortable": True},
                    {"name": "content", "label": "Content", "field": "content", "align": "left", "sortable": True},
                    {"name": "pipeline", "label": "Pipeline", "field": "pipeline", "align": "left", "sortable": True},
                    {"name": "error", "label": "Last error", "field": "error", "align": "left"},
                ]
                index_docs_grid = ui.table(
                    columns=index_docs_cols,
                    rows=[],
                    row_key="id",
                    pagination=25,
                ).classes("w-full").props("dense wrap-cells").style(
                    "background:var(--bg-panel);color:var(--text);font-family:var(--font);"
                )
                index_docs_grid.add_slot("body-cell-status", """
                    <q-td :props="props">
                      <span :style="{color: props.value === 'INDEXED' ? '#10b981' : props.value === 'ERROR' ? '#ef4444' : '#f59e0b', fontWeight:'900'}">
                        {{ props.value }}
                      </span>
                    </q-td>""")
                index_docs_grid.add_slot("body-cell-file", """
                    <q-td :props="props">
                      <div :title="props.value" style="max-width:460px;white-space:normal;word-break:break-word;font-family:var(--font-chat);font-size:.68rem;">
                        {{ props.value }}
                      </div>
                    </q-td>""")
                index_docs_grid.add_slot("body-cell-error", """
                    <q-td :props="props">
                      <span v-if="props.value" :title="props.value" style="color:#ef4444;white-space:normal;word-break:break-word;font-size:.66rem;">
                        {{ props.value }}
                      </span>
                      <span v-else style="color:#64748b;">—</span>
                    </q-td>""")

        # Синк папки-источника: выпадающий список известных папок (+ ручной ввод для новых)
        with ui.row().classes("gap-3 w-full"):
            sync_folder_input = ui.select(
                options=[],
                with_input=True,
                new_value_mode="add-unique",
                label="Папка-источник для синка",
            ).props("dense outlined use-input").style(
                "background:var(--bg);border:1px solid var(--border);color:var(--text);"
                "font-family:var(--font);border-radius:4px;padding:6px 10px;font-size:.75rem;flex:1;"
            ).classes("flex-1")

            async def do_sync():
                folder = (sync_folder_input.value or "").strip()
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
                        "▶ СТАРТ ИНДЕКСАЦИИ",
                        on_click=run_scheduler,
                    ).props("no-caps").style(
                        "background:rgba(245,158,11,.15);border:1px solid var(--warn);"
                        "color:var(--warn);font-size:.7rem;font-weight:900;"
                    )
                    scheduler_live_label = ui.label("○ статус загружается…").style(
                        "color:var(--dim);font-size:.7rem;font-weight:700;"
                    )

        # Live proxy log
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("LIVE LOG // PROXY + INDEXER").classes("section-title")
                live_log_status = ui.label("waiting").style("font-size:.65rem;color:var(--dim);")
            live_log_box = ui.html("", sanitize=False).classes("sov-live-log")

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
            with ui.row().classes("items-center gap-2 w-full"):
                doc_dataset_select = ui.select(
                    {"": "Все датасеты"},
                    value="",
                    label="dataset",
                ).props("dense outlined emit-value map-options").style("min-width:230px;font-size:.7rem;")
                doc_status_select = ui.select(
                    {"": "Все статусы", "ERROR": "ERROR", "PENDING": "PENDING", "INDEXED": "INDEXED"},
                    value="INDEXED",
                    label="status",
                ).props("dense outlined emit-value map-options").style("width:150px;font-size:.7rem;")
                doc_query_input = ui.input(
                    placeholder="Файл, датасет, ошибка..."
                ).props("dense outlined clearable").classes("flex-1").style("font-size:.7rem;")
                doc_limit_select = ui.select(
                    [50, 120, 250, 500],
                    value=120,
                    label="limit",
                ).props("dense outlined").style("width:104px;font-size:.7rem;")
                ui.button(
                    icon="o_filter_alt",
                    on_click=lambda: asyncio.create_task(refresh_documents_only()),
                ).props("flat round dense").tooltip("Применить фильтры")
                ui.button(
                    icon="o_done_all",
                    on_click=lambda: asyncio.create_task(_quick_docs_status("INDEXED")),
                ).props("flat round dense").tooltip("Показать INDEXED")
                ui.button(
                    icon="o_error_outline",
                    on_click=lambda: asyncio.create_task(_quick_docs_status("ERROR")),
                ).props("flat round dense").tooltip("Показать ERROR")
                ui.button(
                    icon="o_pending_actions",
                    on_click=lambda: asyncio.create_task(_quick_docs_status("PENDING")),
                ).props("flat round dense").tooltip("Показать PENDING")
            docs_tbl_cols = [
                {"name": "status", "label": "Статус", "field": "status", "align": "left", "sortable": True},
                {"name": "dataset", "label": "Датасет", "field": "dataset", "align": "left", "sortable": True},
                {"name": "domain", "label": "Domain", "field": "domain", "align": "left", "sortable": True},
                {"name": "route", "label": "Route", "field": "route", "align": "left", "sortable": True},
                {"name": "content", "label": "Content", "field": "content", "align": "left", "sortable": True},
                {"name": "complexity", "label": "Complexity", "field": "complexity", "align": "left", "sortable": True},
                {"name": "chunks", "label": "Чанков", "field": "chunks", "align": "center", "sortable": True},
                {"name": "size", "label": "Размер", "field": "size", "align": "right", "sortable": True},
                {"name": "file", "label": "Файл", "field": "file", "align": "left", "sortable": True},
                {"name": "pipeline", "label": "Pipeline", "field": "pipeline", "align": "left"},
                {"name": "error", "label": "Last error", "field": "error", "align": "left"},
            ]
            docs_grid = ui.table(
                columns=docs_tbl_cols, rows=[], row_key="id", pagination=20
            ).classes("w-full").style(
                "background:var(--bg-panel);color:var(--text);font-family:var(--font);"
            ).props("dense wrap-cells")
            docs_grid.add_slot("body-cell-status", """
                <q-td :props="props">
                  <span :style="{color: props.value === 'INDEXED' ? '#10b981' : props.value === 'ERROR' ? '#ef4444' : '#f59e0b', fontWeight:'800'}">
                    {{ props.value }}
                  </span>
                </q-td>""")
            docs_grid.add_slot("body-cell-file", """
                <q-td :props="props">
                  <div :title="props.value" style="max-width:360px;white-space:normal;word-break:break-word;font-family:var(--font-chat);font-size:.68rem;">
                    {{ props.value }}
                  </div>
                </q-td>""")
            docs_grid.add_slot("body-cell-error", """
                <q-td :props="props">
                  <span v-if="props.value" :title="props.value" style="color:#ef4444;white-space:normal;word-break:break-word;font-size:.66rem;">
                    {{ props.value }}
                  </span>
                  <span v-else style="color:#64748b;">—</span>
                </q-td>""")

        # ── Внутренние функции ──

        def _documents_api_path() -> str:
            params = {
                "limit": int(doc_limit_select.value or 120),
                "offset": 0,
            }
            dataset_id = doc_dataset_select.value or ""
            status = doc_status_select.value or ""
            q = (doc_query_input.value or "").strip()
            if dataset_id:
                params["dataset_id"] = dataset_id
            if status:
                params["status"] = status
            if q:
                params["q"] = q
            return "/api/rag/documents?" + urlencode(params)

        def _format_size(file_size: int) -> str:
            if file_size >= 1024 * 1024:
                return f"{file_size / (1024 * 1024):.1f} MB"
            if file_size >= 1024:
                return f"{file_size / 1024:.0f} KB"
            return f"{file_size} B"

        def _doc_row(item: dict) -> dict:
            return {
                "id": item.get("id", item.get("file_name", "")),
                "status": item.get("status", ""),
                "dataset": item.get("dataset_name", ""),
                "domain": item.get("domain", ""),
                "route": item.get("route_dataset", ""),
                "doc_type": item.get("doc_type", ""),
                "content": item.get("content_type", ""),
                "complexity": item.get("complexity", ""),
                "chunks": item.get("chunk_count", 0),
                "size": _format_size(int(item.get("file_size") or 0)),
                "file": item.get("file_name", ""),
                "pipeline": item.get("pipeline", ""),
                "error": item.get("last_error", ""),
            }

        def _index_documents_api_path() -> str:
            row = selected_index.get("row") or {}
            params = {
                "limit": int(index_limit_select.value or 120),
                "offset": 0,
            }
            dataset_id = row.get("dataset_id") or ""
            status = index_status_select.value or ""
            q = (index_query_input.value or "").strip()
            if dataset_id:
                params["dataset_id"] = dataset_id
            elif row.get("folder"):
                params["q"] = str(row.get("folder"))
            if status:
                params["status"] = status
            if q:
                params["q"] = q
            return "/api/rag/documents?" + urlencode(params)

        async def _refresh_index_dialog_documents(render_main: bool = False):
            row = selected_index.get("row") or {}
            if not row:
                return
            docs = await api_get(_index_documents_api_path())
            if not isinstance(docs, dict):
                ui.notify(last_api_error_text("Ошибка загрузки файлов индекса"), type="negative")
                return
            doc_rows = [_doc_row(item) for item in docs.get("documents", []) if isinstance(item, dict)]
            summary = docs.get("summary", {}) if isinstance(docs.get("summary", {}), dict) else {}
            indexed = summary.get("INDEXED", {})
            pending = summary.get("PENDING", {})
            errors = summary.get("ERROR", {})
            index_kpi["total"].set_text(str(docs.get("total", len(doc_rows))))
            index_kpi["indexed"].set_text(str(indexed.get("files", row.get("indexed", 0))))
            index_kpi["pending"].set_text(str(pending.get("files", row.get("pending", 0))))
            index_kpi["errors"].set_text(str(errors.get("files", row.get("errors", 0))))
            summary_chunks = sum(int(value.get("chunks") or 0) for value in summary.values() if isinstance(value, dict))
            index_kpi["chunks"].set_text(str(summary_chunks or row.get("chunks", 0)))
            index_docs_status.set_text(
                f"shown: {len(doc_rows)}/{docs.get('total', len(doc_rows))} · "
                f"filter: {index_status_select.value or 'ALL'} · q: {(index_query_input.value or '').strip() or '—'}"
            )
            index_docs_grid.rows = doc_rows
            index_docs_grid.update()
            if render_main:
                state["rag_documents"] = docs
                _render()

        async def _open_index_dialog(row):
            if not isinstance(row, dict):
                return
            selected_index["row"] = dict(row)
            name = row.get("folder") or row.get("dataset_id") or "index"
            index_title.set_text(f"INDEX // {name}")
            index_subtitle.set_text(
                " · ".join(
                    part
                    for part in [
                        f"dataset_id: {row.get('dataset_id') or '—'}",
                        f"status: {row.get('status') or '—'}",
                        f"files: {row.get('indexed', 0)}/{row.get('total', 0)}",
                        f"chunks: {row.get('chunks', 0)}",
                    ]
                    if part
                )
            )
            index_query_input.value = ""
            index_status_select.value = ""
            index_query_input.update()
            index_status_select.update()
            index_dialog.open()
            await _refresh_index_dialog_documents()

        async def _quick_index_status(status: str):
            index_status_select.value = status
            index_status_select.update()
            await _refresh_index_dialog_documents()

        async def refresh_documents_only(render: bool = True, notify: bool = True):
            docs = await api_get(_documents_api_path())
            if not isinstance(docs, dict):
                if notify:
                    ui.notify(last_api_error_text("Ошибка загрузки документов"), type="negative")
                return
            docs["source"] = docs.get("source") or "api_active_profile"
            state["rag_documents"] = docs
            if render:
                _render()

        async def _quick_docs_status(status: str):
            doc_status_select.value = status
            doc_status_select.update()
            await refresh_documents_only()

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
            await refresh_documents_only(render=False, notify=False)
            _render()
            _render_live_logs()

        async def refresh_live_logs():
            await refresh_proxy_logs(140)
            _render_live_logs()

        def _render_live_logs():
            lines = list(state.get("proxy_logs") or state.get("logs") or [])[-140:]
            if not lines:
                live_log_box.set_content("<pre>log buffer empty</pre>")
                live_log_status.set_text("empty")
                return
            live_log_status.set_text(f"{len(lines)} lines · live")
            live_log_box.set_content(f"<pre>{escape(chr(10).join(lines))}</pre>")

        def _render():
            sources  = state.get("sources", [])
            rag      = state.get("rag_health", {}) if isinstance(state.get("rag_health"), dict) else {}
            datasets = rag.get("datasets") or state.get("datasets", [])
            totals   = rag.get("totals") or {}
            jobs     = state.get("jobs", {})
            docs     = state.get("rag_documents", {}) if isinstance(state.get("rag_documents"), dict) else {}
            proxy_health = state.get("proxy_health", {}) if isinstance(state.get("proxy_health"), dict) else {}
            indexing_mode = state.get("indexing_mode", {}) if isinstance(state.get("indexing_mode"), dict) else {}
            proxy_status = str(proxy_health.get("status") or "unknown").lower()
            rag_status = str(rag.get("status") or "unknown").lower()
            qdrant = rag.get("qdrant", {}) if isinstance(rag.get("qdrant"), dict) else {}
            parse_blocked = proxy_status == "error" or qdrant.get("ok") is False
            ds_map   = {d["id"]: d for d in datasets}
            dataset_names = {d.get("name", "") for d in datasets}
            dataset_options = {"": "Все датасеты"}
            dataset_options.update(
                {
                    d.get("id", ""): d.get("name", d.get("id", ""))
                    for d in datasets
                    if d.get("id")
                }
            )
            if doc_dataset_select.options != dataset_options:
                doc_dataset_select.options = dataset_options
                if doc_dataset_select.value not in dataset_options:
                    doc_dataset_select.value = ""
                doc_dataset_select.update()

            tot_src = tot_idx = tot_pending = tot_errors = tot_chunks = 0
            rows = []
            seen_ds = set()
            for src in sources:
                folder = src.get("folder", "")
                if not src.get("dataset_id") and any(name.startswith(f"{folder}_") for name in dataset_names):
                    continue
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
                    "folder":     folder,
                    "dataset_id": src.get("dataset_id", ""),
                    "total":      total,
                    "indexed":    indexed,
                    "pending":    pending,
                    "errors":     errors,
                    "chunks":     chunks,
                    "status":     status,
                    "job_info":   job_info,
                    "can_sync":    not parse_blocked,
                    "sync_reason": "парсинг сейчас заблокирован (идёт другая задача)" if parse_blocked else "",
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
                    "sync_reason": "нет папки-источника в RAG_Content — датасет наполняется загрузкой файлов",
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
                if j.get("type") == "rag_parse_scheduler" or "Batch " in str(j.get("message", ""))
            ]
            active_scheduler_jobs = [
                (jid, j) for jid, j in scheduler_jobs
                if str(j.get("status", "")).upper() in {"QUEUED", "PARSING", "RUNNING"}
            ]
            scheduler_candidates = active_scheduler_jobs or scheduler_jobs
            last_scheduler = sorted(
                scheduler_candidates,
                key=lambda item: item[1].get("started_at", ""),
                reverse=True,
            )[0] if scheduler_candidates else None
            mode_state = indexing_mode.get("mode", {}) if isinstance(indexing_mode.get("mode"), dict) else {}
            mode_name = mode_state.get("mode") or ("indexing" if indexing_mode.get("active") else "chat")
            profile_name = indexing_mode.get("runtime_profile") or mode_state.get("runtime_profile") or "CHAT"
            memory_state = indexing_mode.get("memory_state", {}) if isinstance(indexing_mode.get("memory_state"), dict) else {}
            chat_allowed = indexing_mode.get("chat_generation_allowed", True)
            runtime_banner.set_text(
                " · ".join(
                    [
                        f"proxy: {proxy_status}",
                        f"rag: {rag_status}",
                        f"mode: {mode_name}",
                        f"profile: {profile_name}",
                        f"memory: {memory_state.get('state', 'UNKNOWN')}",
                        f"chat: {'allowed' if chat_allowed else 'paused'}",
                        "parse: paused (Qdrant/API health)" if parse_blocked else "parse: available",
                    ]
                )
            )
            if parse_blocked or active_scheduler_jobs:
                start_scheduler_btn.props("disabled")
            else:
                start_scheduler_btn.props(remove="disabled")
            scheduler_status.set_text(
                f"pending: {tot_pending} · errors: {tot_errors} · "
                f"job: {(last_scheduler[0][:12] + ' ' + last_scheduler[1].get('status','')) if last_scheduler else '—'}"
                + (" · старт заблокирован preflight guard" if parse_blocked else "")
            )
            sam_grid.rows = rows
            sam_grid.update()

            # Опции синка: известные папки-источники (где синк возможен)
            sync_folder_input.options = sorted({r["folder"] for r in rows if r.get("can_sync")})
            sync_folder_input.update()

            # Живость шедулера: активные parse-задачи рядом с кнопкой START
            active_jobs = [j for j in jobs.values() if str(j.get("status", "")).upper() in ("RUNNING", "QUEUED", "STARTED")]
            if active_jobs:
                current = active_jobs[0]
                scheduler_live_label.set_text(
                    f"● РАБОТАЕТ: {current.get('dataset_name', '?')} {current.get('processed', 0)}/{current.get('total', 0)}"
                    + (f" (+{len(active_jobs) - 1} в очереди)" if len(active_jobs) > 1 else "")
                )
                scheduler_live_label.style("color:var(--ok);font-size:.7rem;font-weight:700;")
            else:
                scheduler_live_label.set_text("○ не запущен")
                scheduler_live_label.style("color:var(--dim);font-size:.7rem;font-weight:700;")

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
                doc_rows.append(_doc_row(item))
            summary = docs.get("summary", {}) if isinstance(docs, dict) else {}
            docs_source = docs.get("source", "") if isinstance(docs, dict) else ""
            docs_total = docs.get("total", len(doc_rows)) if isinstance(docs, dict) else len(doc_rows)
            docs_status.set_text(
                f"shown: {len(doc_rows)}/{docs_total} · "
                + " · ".join(
                    f"{key}: {value.get('files', 0)}"
                    for key, value in summary.items()
                )
                + (f" · source: {docs_source}" if docs_source else "")
                or "INDEXED/PENDING/ERROR"
            )
            docs_grid.rows = doc_rows
            docs_grid.update()

        index_query_input.on("keydown.enter", lambda e: asyncio.create_task(_refresh_index_dialog_documents()))
        doc_query_input.on("keydown.enter", lambda e: asyncio.create_task(refresh_documents_only()))

        # Загружаем при входе без одноразового timer, чтобы обновление не
        # прилетало в уже удалённый slot при быстрой навигации.
        asyncio.create_task(refresh_and_render())
        live_logs_timer = ui.timer(3.0, lambda: asyncio.create_task(refresh_live_logs()))
        context.client.on_disconnect(lambda *_: live_logs_timer.cancel())
