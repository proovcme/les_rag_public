"""No-AI document browser for LES datasets.

This page is an operator surface: dataset -> document -> chunks/search. It
does not ask the model anything; it makes the indexed corpus visible.
"""
from __future__ import annotations

import asyncio
import json
from urllib.parse import quote, urlencode

from nicegui import ui

from sovushka.state import api_get, add_log, last_api_error_text


def build_documents() -> None:
    state = {
        "datasets": [],
        "documents": [],
        "chunks": [],
        "hits": [],
        "selected_dataset": "",
        "selected_doc_id": "",
        "selected_doc_name": "",
        "dataset_filter": "",
        "document_filter": "",
        "query": "",
        "view_title": "Выберите датасет",
        "view_note": "Документы читаются из SQLite/Qdrant-индекса без участия модели.",
    }
    refs: dict[str, object] = {}

    def _schedule(coro):
        asyncio.create_task(coro)

    def _label(text: str, *, size: str = "12px", color: str = "var(--text)", weight: int = 500):
        return ui.label(text).style(f"font-size:{size};color:{color};font-weight:{weight};")

    def _badge(text: str, cls: str = "tag-dim"):
        return ui.label(text).classes(cls)

    def _format_size(value: int | float | str | None) -> str:
        try:
            n = float(value or 0)
        except (TypeError, ValueError):
            return "0 Б"
        units = ["Б", "КБ", "МБ", "ГБ"]
        i = 0
        while n >= 1024 and i < len(units) - 1:
            n /= 1024
            i += 1
        return f"{n:.1f} {units[i]}" if i else f"{int(n)} {units[i]}"

    def _dataset_title(row: dict) -> str:
        name = str(row.get("name") or row.get("id") or "")
        did = str(row.get("id") or "")
        return name if name == did else f"{name} · {did}"

    async def _load_datasets(select_first: bool = True) -> None:
        params = {"limit": 400}
        if state["dataset_filter"].strip():
            params["q"] = state["dataset_filter"].strip()
        data = await api_get("/api/documents/datasets?" + urlencode(params))
        if not isinstance(data, dict):
            _render_status_error()
            return
        state["datasets"] = list(data.get("datasets") or [])
        if select_first and state["datasets"] and not state["selected_dataset"]:
            await _select_dataset(str(state["datasets"][0].get("id") or ""))
        else:
            _render_datasets()
            _render_documents()
            _render_view()

    async def _select_dataset(dataset_id: str) -> None:
        state["selected_dataset"] = dataset_id
        state["selected_doc_id"] = ""
        state["selected_doc_name"] = ""
        state["chunks"] = []
        state["hits"] = []
        state["view_title"] = dataset_id or "Выберите датасет"
        state["view_note"] = "Выберите документ или запустите поиск по выбранному датасету."
        await _load_documents()

    async def _load_documents() -> None:
        dataset_id = state["selected_dataset"]
        if not dataset_id:
            state["documents"] = []
            _render_all()
            return
        params = {"limit": 500}
        if state["document_filter"].strip():
            params["q"] = state["document_filter"].strip()
        path = f"/api/documents/datasets/{quote(dataset_id, safe='')}/documents?{urlencode(params)}"
        data = await api_get(path)
        if not isinstance(data, dict):
            _render_status_error()
            return
        state["documents"] = list(data.get("documents") or [])
        _render_all()

    async def _open_document(doc_id: str) -> None:
        if not doc_id:
            return
        path = f"/api/documents/by-id/{quote(doc_id, safe='')}/chunks?" + urlencode(
            {"limit": 120, "max_chars": 9000}
        )
        data = await api_get(path)
        if not isinstance(data, dict):
            _render_status_error()
            return
        doc = data.get("document") or {}
        state["selected_doc_id"] = doc_id
        state["selected_doc_name"] = str(doc.get("file_name") or data.get("doc_name") or "")
        state["chunks"] = list(data.get("chunks") or [])
        state["hits"] = []
        state["view_title"] = state["selected_doc_name"] or doc_id
        state["view_note"] = f"{data.get('total', 0)} фрагментов в документе. Показаны первые {len(state['chunks'])}."
        _render_all()

    async def _search(scope: str) -> None:
        query = state["query"].strip()
        if not query:
            ui.notify("Введите поисковую фразу", type="warning")
            return
        params: dict[str, object] = {"q": query, "limit": 80, "max_chars": 2200}
        if scope == "dataset" and state["selected_dataset"]:
            params["dataset_id"] = [state["selected_dataset"]]
        if scope == "document" and state["selected_doc_id"]:
            params["doc_id"] = state["selected_doc_id"]
        query_string = urlencode(params, doseq=True)
        data = await api_get("/api/documents/search?" + query_string)
        if not isinstance(data, dict):
            _render_status_error()
            return
        state["hits"] = list(data.get("hits") or [])
        state["chunks"] = []
        scope_label = {
            "document": "в документе",
            "dataset": "в датасете",
            "all": "во всём индексе",
        }.get(scope, "в индексе")
        state["view_title"] = f"Поиск {scope_label}: {query}"
        state["view_note"] = f"Найдено {data.get('count', len(state['hits']))}. Источник: lexical SQLite/FTS."
        _render_view()

    def _copy_sources() -> None:
        rows = state["hits"] or state["chunks"]
        if not rows:
            ui.notify("Нет выбранных фрагментов для списка источников", type="warning")
            return
        sources = []
        for item in rows[:80]:
            sources.append(
                {
                    "dataset_id": item.get("dataset_id"),
                    "document": item.get("doc_name"),
                    "chunk": item.get("chunk_ord"),
                    "point_id": item.get("point_id"),
                    "section": item.get("section_heading") or item.get("parent_heading") or "",
                }
            )
        text = json.dumps(sources, ensure_ascii=False, indent=2)
        ui.run_javascript(f"navigator.clipboard.writeText({json.dumps(text, ensure_ascii=False)})")
        ui.notify("Список источников скопирован", type="positive")

    def _render_status_error() -> None:
        err = last_api_error_text() or "proxy не вернул данные документов"
        add_log(f"[DOCS] {err}")
        ui.notify(err, type="negative")

    def _render_datasets() -> None:
        panel = refs.get("datasets")
        if panel is None:
            return
        panel.clear()
        with panel:
            if not state["datasets"]:
                _label("Датасетов не найдено", color="var(--dim)")
                return
            for row in state["datasets"]:
                did = str(row.get("id") or "")
                selected = did == state["selected_dataset"]
                with ui.element("div").classes("w-full").style(
                    "border:1px solid var(--border);border-radius:7px;padding:9px 10px;"
                    f"background:{'var(--bg-mod)' if selected else 'var(--bg-panel)'};cursor:pointer;"
                ).on("click", lambda _e, value=did: _schedule(_select_dataset(value))):
                    with ui.row().classes("items-center w-full").style("gap:7px;flex-wrap:nowrap;"):
                        ui.icon("o_dataset").style("font-size:17px;color:var(--accent);")
                        _label(_dataset_title(row), size="12.5px", weight=800).style(
                            "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;"
                        )
                    with ui.row().classes("items-center").style("gap:5px;margin-top:6px;flex-wrap:wrap;"):
                        _badge(str(row.get("status") or "status?"), "tag-acc" if str(row.get("status", "")).upper() in {"IDLE", "INDEXED"} else "tag-dim")
                        _badge(f"{int(row.get('document_count') or 0)} док.")
                        _badge(f"{int(row.get('chunk_count') or 0)} фраг.")

    def _render_documents() -> None:
        panel = refs.get("documents")
        if panel is None:
            return
        panel.clear()
        with panel:
            if not state["selected_dataset"]:
                _label("Сначала выберите датасет", color="var(--dim)")
                return
            if not state["documents"]:
                _label("Документы не найдены", color="var(--dim)")
                return
            for row in state["documents"]:
                doc_id = str(row.get("id") or "")
                selected = doc_id == state["selected_doc_id"]
                with ui.element("div").classes("w-full").style(
                    "border:1px solid var(--border);border-radius:7px;padding:9px 10px;"
                    f"background:{'var(--bg-mod)' if selected else 'var(--bg-panel)'};cursor:pointer;"
                ).on("click", lambda _e, value=doc_id: _schedule(_open_document(value))):
                    with ui.row().classes("items-center w-full").style("gap:7px;flex-wrap:nowrap;"):
                        ui.icon("o_description").style("font-size:17px;color:var(--accent);")
                        _label(str(row.get("file_name") or doc_id), size="12px", weight=800).style(
                            "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;"
                        )
                    with ui.row().classes("items-center").style("gap:5px;margin-top:6px;flex-wrap:wrap;"):
                        _badge(str(row.get("status") or "status?"), "tag-acc" if str(row.get("status", "")).upper() == "INDEXED" else "tag-warn")
                        if row.get("doc_type"):
                            _badge(str(row.get("doc_type")))
                        if row.get("content_type"):
                            _badge(str(row.get("content_type")))
                        _badge(f"{int(row.get('chunk_count') or 0)} фраг.")
                        _badge(_format_size(row.get("file_size")))
                    if row.get("last_error"):
                        _label(str(row["last_error"])[:180], size="11px", color="var(--err)")

    def _render_view() -> None:
        panel = refs.get("view")
        if panel is None:
            return
        panel.clear()
        with panel:
            with ui.row().classes("items-center w-full").style("gap:8px;margin-bottom:8px;"):
                ui.icon("o_article").style("font-size:19px;color:var(--accent);")
                _label(state["view_title"], size="14px", weight=900).style(
                    "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;"
                )
                ui.button(icon="o_content_copy", on_click=_copy_sources).props(
                    'flat dense round aria-label="Скопировать источники"'
                ).tooltip("Скопировать список источников")
            _label(state["view_note"], size="11.5px", color="var(--dim)")

            rows = state["hits"] or state["chunks"]
            if not rows:
                with ui.element("div").style(
                    "border:1px dashed var(--border);border-radius:8px;padding:18px;margin-top:12px;"
                ):
                    _label(
                        "Здесь будет текст документа или результаты поиска. Пока пусто, зато честно.",
                        color="var(--dim)",
                    )
                return

            for item in rows:
                title = item.get("section_heading") or item.get("parent_heading") or item.get("doc_name") or "фрагмент"
                text = str(item.get("snippet") or item.get("text") or "")
                with ui.element("div").classes("w-full").style(
                    "border-bottom:1px solid var(--border);padding:12px 0;"
                ):
                    with ui.row().classes("items-center w-full").style("gap:6px;flex-wrap:wrap;"):
                        _badge(f"chunk {item.get('chunk_ord')}", "tag-acc")
                        if item.get("rank"):
                            _badge(f"rank {item.get('rank')}")
                        _label(str(title), size="12px", weight=800).style(
                            "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:160px;flex:1;"
                        )
                    _label(str(item.get("doc_name") or ""), size="11px", color="var(--dim)").style(
                        "margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                    )
                    ui.label(text).style(
                        "white-space:pre-wrap;font-size:12px;line-height:1.5;color:var(--text);"
                        "margin-top:8px;font-family:var(--font-chat);"
                    )

    def _render_all() -> None:
        _render_datasets()
        _render_documents()
        _render_view()

    with ui.column().classes("w-full h-full gap-0").style("min-height:calc(100vh - 112px);background:var(--bg);"):
        with ui.row().classes("items-center w-full").style(
            "gap:10px;padding:12px 16px;border-bottom:1px solid var(--border);background:var(--bg-panel);"
        ):
            ui.icon("o_folder_open").style("font-size:20px;color:var(--accent);")
            _label("Документы", size="15px", weight=900)
            _label("датасет → документ → фрагменты, без модели", size="11.5px", color="var(--dim)")
            ui.element("div").style("flex:1;")
            q_input = ui.input(placeholder="поиск по корпусу, датасету или документу").props("dense outlined clearable").style(
                "min-width:320px;max-width:520px;flex:1;background:var(--input-bg);"
            )
            q_input.on("update:model-value", lambda e: state.__setitem__("query", str(e.args or "")))
            q_input.on("keydown.enter", lambda _e: _schedule(_search("dataset" if state["selected_dataset"] else "all")))
            ui.button(icon="o_search", on_click=lambda: _schedule(_search("dataset" if state["selected_dataset"] else "all"))).props(
                'flat dense round aria-label="Искать"'
            ).tooltip("Искать в выбранном датасете или во всём индексе")
            ui.button(icon="o_find_in_page", on_click=lambda: _schedule(_search("document"))).props(
                'flat dense round aria-label="Искать в документе"'
            ).tooltip("Искать в открытом документе")
            ui.button(icon="o_refresh", on_click=lambda: _schedule(_load_datasets(select_first=False))).props(
                'flat dense round aria-label="Обновить"'
            ).tooltip("Обновить список")

        with ui.row().classes("w-full flex-1 no-wrap").style("min-height:0;overflow:hidden;"):
            with ui.column().classes("h-full no-wrap").style(
                "width:300px;min-width:260px;border-right:1px solid var(--border);padding:12px;gap:10px;overflow:hidden;"
            ):
                _label("Датасеты", size="12px", color="var(--dim)", weight=900)
                dataset_filter = ui.input(placeholder="фильтр").props("dense outlined clearable").style("width:100%;")
                dataset_filter.on("update:model-value", lambda e: state.__setitem__("dataset_filter", str(e.args or "")))
                dataset_filter.on("keydown.enter", lambda _e: _schedule(_load_datasets(select_first=True)))
                with ui.column().classes("w-full gap-2").style("overflow:auto;min-height:0;flex:1;") as datasets_panel:
                    refs["datasets"] = datasets_panel

            with ui.column().classes("h-full no-wrap").style(
                "width:390px;min-width:320px;border-right:1px solid var(--border);padding:12px;gap:10px;overflow:hidden;"
            ):
                _label("Документы", size="12px", color="var(--dim)", weight=900)
                document_filter = ui.input(placeholder="фильтр по имени файла").props("dense outlined clearable").style("width:100%;")
                document_filter.on("update:model-value", lambda e: state.__setitem__("document_filter", str(e.args or "")))
                document_filter.on("keydown.enter", lambda _e: _schedule(_load_documents()))
                with ui.column().classes("w-full gap-2").style("overflow:auto;min-height:0;flex:1;") as documents_panel:
                    refs["documents"] = documents_panel

            with ui.column().classes("h-full no-wrap").style(
                "flex:1;min-width:0;padding:12px 16px;overflow:auto;"
            ) as view_panel:
                refs["view"] = view_panel

    ui.timer(0.15, lambda: _schedule(_load_datasets()), once=True)
