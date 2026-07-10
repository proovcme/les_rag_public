"""No-AI document browser for LES datasets.

This page is an operator surface: dataset -> document -> chunks/search. It
does not ask the model anything; it makes the indexed corpus visible.
"""
from __future__ import annotations

import asyncio
import json
from urllib.parse import quote, urlencode

from nicegui import context, ui

from sovushka.state import api_get, api_patch, api_post, add_log, last_api_error_text

DATASET_KIND_OPTIONS = {
    "": "Все типы",
    "project": "Проекты",
    "norm": "Нормы",
    "estimate": "Сметы",
    "catalog": "Каталоги",
    "cad_bim": "CAD/BIM",
    "correspondence": "Переписка",
    "mixed": "Смешанные",
    "other": "Другое",
}
DATASET_KIND_EDIT_OPTIONS = {
    "": "Не помечен",
    "project": "Проект",
    "norm": "Норма",
    "estimate": "Сметы",
    "catalog": "Каталог",
    "cad_bim": "CAD/BIM",
    "correspondence": "Переписка",
    "mixed": "Смешанный",
    "other": "Другое",
}


def build_documents() -> None:
    state = {
        "datasets": [],
        "documents": [],
        "chunks": [],
        "hits": [],
        "dataset_memory": {},
        "memory_loading": False,
        "operator_guidance": "",
        "dataset_kind": "",
        "tool_registry": {},
        "tool_result": {},
        "tool_running": False,
        "pdf_extract": {},
        "pdf_extract_loading": False,
        "cad_inventory": {},
        "cad_loading": False,
        "view_mode": "map",
        "selected_dataset": "",
        "selected_doc_id": "",
        "selected_doc_name": "",
        "dataset_filter": "",
        "dataset_kind_filter": "",
        "document_filter": "",
        "project_filter": "",
        "query": "",
        "view_title": "Выберите датасет",
        "view_note": "Л.И.С.Т.: карта проекта, файлы и быстрые вопросы по выбранным источникам.",
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

    def _selected_dataset_row() -> dict:
        dataset_id = str(state.get("selected_dataset") or "")
        for row in state.get("datasets") or []:
            if str(row.get("id") or "") == dataset_id:
                return row
        return {}

    def _document_by_id(doc_id: str) -> dict:
        doc_id = str(doc_id or "")
        for row in state.get("documents") or []:
            if str(row.get("id") or "") == doc_id:
                return row
        return {}

    def _document_by_file_name(file_name: str) -> dict:
        file_name = str(file_name or "")
        basename = file_name.rsplit("/", 1)[-1]
        for row in state.get("documents") or []:
            row_name = str(row.get("file_name") or "")
            if row_name == file_name or row_name == basename or row_name.endswith("/" + basename):
                return row
        return {}

    def _dataset_kind_label(kind: str) -> str:
        return DATASET_KIND_EDIT_OPTIONS.get(str(kind or ""), "")

    def _selected_dataset_kind() -> str:
        memory = state.get("dataset_memory") if isinstance(state.get("dataset_memory"), dict) else {}
        row = _selected_dataset_row()
        return str(memory.get("dataset_kind") or row.get("dataset_kind") or state.get("dataset_kind") or "")

    def _source_map_files(memory: dict, project_pdf: dict) -> list[dict]:
        files = [item for item in (project_pdf.get("files") or []) if isinstance(item, dict)]
        if not files and isinstance(memory.get("project_pdf_extract"), dict):
            files = [item for item in (memory.get("project_pdf_extract", {}).get("files") or []) if isinstance(item, dict)]
        if files:
            return files
        result: list[dict] = []
        for row in state.get("documents") or []:
            file_name = str(row.get("file_name") or "")
            result.append(
                {
                    "file_name": file_name,
                    "doc_id": str(row.get("id") or ""),
                    "doc_role": str(row.get("doc_type") or row.get("content_type") or "документ"),
                    "discipline": str(row.get("domain") or ""),
                    "source_path": str(row.get("source_path") or ""),
                    "status": "ok" if str(row.get("status") or "").upper() == "INDEXED" else str(row.get("status") or ""),
                    "layers": [str(row.get("content_type") or "")] if row.get("content_type") else [],
                }
            )
        return result

    def _file_group_key(item: dict) -> tuple[str, str]:
        section = str(item.get("discipline") or item.get("domain") or item.get("route_dataset") or "").strip()
        if not section:
            file_name = str(item.get("file_name") or "")
            section = file_name.split("/", 1)[0] if "/" in file_name else "без раздела"
        role = str(item.get("doc_role") or item.get("document_role") or item.get("doc_type") or item.get("content_type") or "").strip()
        if not role:
            suffix = str(item.get("file_name") or "").rsplit(".", 1)
            role = suffix[-1].upper() if len(suffix) > 1 else "документ"
        return section, role

    def _file_registry(files: list[dict]) -> list[dict]:
        groups: dict[tuple[str, str], dict] = {}
        for item in files:
            section, role = _file_group_key(item)
            group = groups.setdefault(
                (section, role),
                {"section": section, "role": role, "files": 0, "warnings": 0, "samples": []},
            )
            group["files"] += 1
            if item.get("warnings") or str(item.get("status") or "").lower() in {"error", "missing"}:
                group["warnings"] += 1
            if len(group["samples"]) < 4:
                group["samples"].append(str(item.get("file_name") or ""))
        return sorted(groups.values(), key=lambda item: (str(item.get("section") or ""), -int(item.get("files") or 0), str(item.get("role") or "")))

    def _short_path(value: str, *, parts: int = 3) -> str:
        chunks = [x for x in str(value or "").split("/") if x]
        if len(chunks) <= parts:
            return str(value or "")
        return ".../" + "/".join(chunks[-parts:])

    def _project_roots(files: list[dict]) -> list[dict]:
        roots: dict[str, dict] = {}
        for item in files:
            file_name = str(item.get("file_name") or "")
            root_name = file_name.split("/", 1)[0] if "/" in file_name else "без папки"
            row = roots.setdefault(
                root_name,
                {
                    "name": root_name,
                    "files": 0,
                    "ok": 0,
                    "warnings": 0,
                    "roles": {},
                    "disciplines": {},
                },
            )
            row["files"] += 1
            if str(item.get("status") or "") == "ok":
                row["ok"] += 1
            if item.get("warnings"):
                row["warnings"] += 1
            role = str(item.get("doc_role") or "PDF")
            discipline = str(item.get("discipline") or "")
            row["roles"][role] = int(row["roles"].get(role) or 0) + 1
            if discipline:
                row["disciplines"][discipline] = int(row["disciplines"].get(discipline) or 0) + 1
        return sorted(roots.values(), key=lambda item: (-int(item.get("files") or 0), str(item.get("name") or "")))

    def _mermaid_label(value: object, *, limit: int = 54) -> str:
        text = str(value or "").replace("\n", " ").replace("\r", " ").strip()
        text = " ".join(text.split())
        if len(text) > limit:
            text = text[: limit - 1].rstrip() + "…"
        return text.replace('"', "'")

    def _dataset_structure_mermaid(memory: dict, project_pdf: dict, coverage: dict, files: list[dict]) -> str:
        selected = _selected_dataset_row()
        dataset_title = selected.get("name") or state.get("selected_dataset") or "Датасет"
        roots = _project_roots(files)
        disciplines = [
            item for item in (project_pdf.get("discipline_summaries") or []) if isinstance(item, dict)
        ]
        table_summary = coverage.get("project_table_summary") if isinstance(coverage.get("project_table_summary"), dict) else {}
        electrical_summary = coverage.get("electrical_summary") if isinstance(coverage.get("electrical_summary"), dict) else {}
        found_rows = [
            ("Документов", selected.get("document_count") or memory.get("document_count") or len(state.get("documents") or [])),
            ("PDF", coverage.get("pdf_documents")),
            ("Текстовых частей", selected.get("chunk_count") or memory.get("chunk_count")),
            ("Таблиц", table_summary.get("detected_tables")),
            ("ПЗ", coverage.get("pz_files")),
            ("ВОР", coverage.get("vor_files")),
            ("СО", coverage.get("so_files")),
            ("Экспликаций", table_summary.get("room_explication_rows")),
            ("Водных балансов", table_summary.get("water_balance_rows")),
            ("ХВС", table_summary.get("hvs_rows")),
            ("Электрика", electrical_summary.get("files") or electrical_summary.get("load_tables")),
        ]
        lines = [
            "flowchart LR",
            f'    ds["{_mermaid_label(dataset_title, limit=48)}"]',
            '    roots["Проекты и папки"]',
            '    discs["Разделы"]',
            '    found["Что найдено"]',
            "    ds --> roots",
            "    ds --> discs",
            "    ds --> found",
        ]
        if roots:
            for index, root in enumerate(roots[:6]):
                status = " · проверить" if root.get("warnings") else ""
                label = f"{root.get('name') or 'папка'} · {root.get('files', 0)} PDF{status}"
                lines.append(f'    root{index}["{_mermaid_label(label)}"]')
                lines.append(f"    roots --> root{index}")
        else:
            lines.extend(['    root0["Файлы пока не разобраны"]', "    roots --> root0"])

        if disciplines:
            for index, item in enumerate(disciplines[:8]):
                label = f"{item.get('discipline') or 'Раздел'} · {int(item.get('files') or 0)} файлов"
                lines.append(f'    disc{index}["{_mermaid_label(label)}"]')
                lines.append(f"    discs --> disc{index}")
        else:
            lines.extend(['    disc0["Разделы появятся после чтения PDF"]', "    discs --> disc0"])

        added = 0
        for title, value in found_rows:
            try:
                count = int(value or 0)
            except (TypeError, ValueError):
                count = 0
            if count <= 0:
                continue
            lines.append(f'    found{added}["{_mermaid_label(title)}: {count}"]')
            lines.append(f"    found --> found{added}")
            added += 1
            if added >= 10:
                break
        if not added:
            lines.extend(['    found0["Карта появится после разбора PDF"]', "    found --> found0"])

        warnings = int(coverage.get("extract_errors") or 0) + int(coverage.get("missing_source") or 0)
        unknown_tables = 0
        try:
            unknown_tables = int((table_summary.get("by_type") or {}).get("UNKNOWN") or 0)
        except (TypeError, ValueError, AttributeError):
            unknown_tables = 0
        if warnings or unknown_tables:
            lines.extend(['    check["Что проверить"]', "    ds --> check"])
            if warnings:
                lines.append(f'    checkFiles["PDF: {warnings}"]')
                lines.append("    check --> checkFiles")
            if unknown_tables:
                lines.append(f'    checkTables["Таблицы: {unknown_tables}"]')
                lines.append("    check --> checkTables")
        lines.extend(
            [
                "    classDef main fill:#eff6ff,stroke:#3b82f6,color:#0f172a,stroke-width:1px;",
                "    classDef group fill:#f8fafc,stroke:#94a3b8,color:#0f172a;",
                "    classDef warn fill:#fff7ed,stroke:#f97316,color:#7c2d12;",
                "    class ds main;",
                "    class roots,discs,found group;",
                "    class check,checkFiles,checkTables warn;",
            ]
        )
        return "\n".join(lines)

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
        state["dataset_memory"] = {}
        state["memory_loading"] = False
        state["pdf_extract"] = {}
        state["pdf_extract_loading"] = False
        state["operator_guidance"] = ""
        state["dataset_kind"] = str(_selected_dataset_row().get("dataset_kind") or "")
        state["view_mode"] = "map"
        state["view_title"] = dataset_id or "Выберите датасет"
        state["view_note"] = "Л.И.С.Т.: что найдено, где искать и какие файлы открыть."
        await _load_documents()
        await _load_memory()
        await _load_pdf_extract_summary()

    async def _load_memory() -> None:
        dataset_id = state["selected_dataset"]
        if not dataset_id:
            state["dataset_memory"] = {}
            _render_view()
            return
        state["memory_loading"] = True
        _render_view()
        data = await api_get(f"/api/notebooks/{quote(dataset_id, safe='')}/memory")
        state["memory_loading"] = False
        if not isinstance(data, dict):
            _render_status_error()
            return
        state["dataset_memory"] = data
        state["operator_guidance"] = str(data.get("operator_guidance") or "")
        state["dataset_kind"] = str(data.get("dataset_kind") or state.get("dataset_kind") or "")
        _render_view()

    async def _refresh_memory() -> None:
        dataset_id = state["selected_dataset"]
        if not dataset_id:
            ui.notify("Сначала выберите датасет", type="warning")
            return
        state["memory_loading"] = True
        _render_view()
        data = await api_post(f"/api/notebooks/{quote(dataset_id, safe='')}/memory/refresh")
        state["memory_loading"] = False
        if not isinstance(data, dict):
            _render_status_error()
            return
        state["dataset_memory"] = data
        state["operator_guidance"] = str(data.get("operator_guidance") or "")
        state["dataset_kind"] = str(data.get("dataset_kind") or state.get("dataset_kind") or "")
        ui.notify("Карта датасета обновлена", type="positive")
        _render_view()

    async def _load_pdf_extract_summary() -> None:
        dataset_id = state["selected_dataset"]
        if not dataset_id:
            ui.notify("Сначала выберите датасет", type="warning")
            return
        state["pdf_extract_loading"] = True
        _render_view()
        data = await api_get(f"/api/rag/datasets/{quote(dataset_id, safe='')}/pdf-extract/summary")
        state["pdf_extract_loading"] = False
        if not isinstance(data, dict):
            _render_status_error()
            _render_view()
            return
        state["pdf_extract"] = data
        _render_view()

    async def _run_pdf_extract() -> None:
        dataset_id = state["selected_dataset"]
        if not dataset_id:
            ui.notify("Сначала выберите датасет", type="warning")
            return
        state["pdf_extract_loading"] = True
        _render_view()
        params = urlencode({"force": "true", "max_files": 80, "max_pages": 260})
        data = await api_post(f"/api/rag/datasets/{quote(dataset_id, safe='')}/pdf-extract/run?{params}")
        state["pdf_extract_loading"] = False
        if not isinstance(data, dict):
            _render_status_error()
            _render_view()
            return
        state["pdf_extract"] = data
        ui.notify("Карта PDF обновлена", type="positive")
        await _refresh_memory()

    async def _load_tools() -> None:
        data = await api_get("/api/tools/registry")
        if isinstance(data, dict):
            state["tool_registry"] = data
            _render_view()
        else:
            _render_status_error()

    async def _load_cad_inventory() -> None:
        state["cad_loading"] = True
        state["view_mode"] = "cad"
        state["view_title"] = "CAD/BIM imports"
        state["view_note"] = "Read-only сверка CAD graph DB и CAD_BIM_Index: импорты, projection, слабые графы и дубли."
        _render_view()
        data = await api_get("/api/cad-bim/imports?limit=300")
        state["cad_loading"] = False
        if not isinstance(data, dict):
            _render_status_error()
            _render_view()
            return
        state["cad_inventory"] = data
        _render_view()

    async def _run_tool(tool: str, args: dict) -> None:
        state["tool_running"] = True
        state["tool_result"] = {}
        _render_view()
        data = await api_post("/api/tools/call", {"tool": tool, "args": args})
        state["tool_running"] = False
        if not isinstance(data, dict):
            _render_status_error()
            _render_view()
            return
        state["tool_result"] = data
        _render_view()

    async def _run_tool_shortlist() -> None:
        state["tool_running"] = True
        state["tool_result"] = {}
        _render_view()
        data = await api_post(
            "/api/tools/shortlist",
            {
                "question": state["query"].strip() or state["view_title"],
                "mode": state["view_mode"],
                "limit": 8,
            },
        )
        state["tool_running"] = False
        if not isinstance(data, dict):
            _render_status_error()
            _render_view()
            return
        state["tool_result"] = {
            "schema": data.get("schema") or "les_tool_shortlist_v1",
            "tool": "shortlist",
            "operation": "shortlist",
            "status": "ok" if data.get("tools") else "missing",
            "result": data,
            "sources": [],
            "missing": [] if data.get("tools") else ["no tools shortlisted"],
            "warnings": [],
            "trace": "shortlisted tools from the current query/mode; model would choose calls from this list",
            "contract_check": {"ok": True, "warnings": []},
        }
        _render_view()

    def _tool_search_args() -> dict:
        args = {"q": state["query"].strip() or state["view_title"], "limit": 20, "max_chars": 1200}
        if state["selected_dataset"]:
            args["dataset_ids"] = [state["selected_dataset"]]
        if state["selected_doc_id"]:
            args["doc_id"] = state["selected_doc_id"]
        return args

    def _tool_read_args() -> dict:
        if state["selected_doc_id"]:
            return {"doc_id": state["selected_doc_id"], "limit": 20, "max_chars": 2200}
        return {"dataset_id": state["selected_dataset"], "doc_name": state["selected_doc_name"], "limit": 20}

    async def _save_guidance() -> None:
        dataset_id = state["selected_dataset"]
        if not dataset_id:
            ui.notify("Сначала выберите датасет", type="warning")
            return
        payload = {"guidance": state["operator_guidance"], "depth": "deep"}
        data = await api_patch(f"/api/rag/datasets/{quote(dataset_id, safe='')}/profile/guidance", payload)
        if not isinstance(data, dict):
            _render_status_error()
            return
        memory = dict(state.get("dataset_memory") or {})
        memory["operator_guidance"] = str(data.get("operator_guidance") or "")
        memory["operator_guidance_role"] = str(data.get("operator_guidance_role") or "navigation_not_evidence")
        state["dataset_memory"] = memory
        state["operator_guidance"] = memory["operator_guidance"]
        ui.notify("Пояснение для модели сохранено", type="positive")
        _render_view()

    async def _save_dataset_kind(kind: str) -> None:
        dataset_id = state["selected_dataset"]
        if not dataset_id:
            ui.notify("Сначала выберите датасет", type="warning")
            return
        normalized = str(kind or "")
        data = await api_patch(
            f"/api/rag/datasets/{quote(dataset_id, safe='')}/profile/kind",
            {"kind": normalized, "depth": "deep"},
        )
        if not isinstance(data, dict):
            _render_status_error()
            return
        stored_kind = str(data.get("dataset_kind") or "")
        stored_label = str(data.get("dataset_kind_label") or "")
        state["dataset_kind"] = stored_kind
        memory = dict(state.get("dataset_memory") or {})
        memory["dataset_kind"] = stored_kind
        memory["dataset_kind_label"] = stored_label
        state["dataset_memory"] = memory
        for row in state.get("datasets") or []:
            if str(row.get("id") or "") == dataset_id:
                row["dataset_kind"] = stored_kind
                row["dataset_kind_label"] = stored_label
                break
        ui.notify("Тип датасета сохранён", type="positive")
        _render_all()

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
        state["view_mode"] = "fragments"
        state["view_title"] = state["selected_doc_name"] or doc_id
        state["view_note"] = f"{data.get('total', 0)} частей документа. Показаны первые {len(state['chunks'])}."
        _render_all()

    async def _open_native_document(doc_id: str) -> None:
        if not doc_id:
            ui.notify("Документ не найден в индексе", type="warning")
            return
        data = await api_post(f"/api/documents/by-id/{quote(doc_id, safe='')}/open-native")
        if not isinstance(data, dict):
            _render_status_error()
            return
        if data.get("status") == "opened":
            ui.notify("Файл открыт системно", type="positive")
        else:
            ui.notify(str(data.get("status") or "Не удалось открыть файл"), type="warning")

    async def _open_native_file_name(file_name: str, doc_id: str = "") -> None:
        doc_id = str(doc_id or "").strip()
        if not doc_id:
            doc = _document_by_file_name(file_name)
            doc_id = str(doc.get("id") or "").strip()
        await _open_native_document(doc_id)

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
        state["view_mode"] = "fragments"
        scope_label = {
            "document": "в документе",
            "dataset": "в датасете",
            "all": "во всём индексе",
        }.get(scope, "в индексе")
        state["view_title"] = f"Поиск {scope_label}: {query}"
        state["view_note"] = f"Найдено {data.get('count', len(state['hits']))}. Источник: lexical SQLite/FTS."
        _render_view()

    def _show_map() -> None:
        state["view_mode"] = "map"
        state["view_title"] = state["selected_dataset"] or "Выберите датасет"
        state["view_note"] = "Л.И.С.Т. показывает карту корпуса: описание, проекты, тома, файлы и маршруты чтения."
        _render_view()

    def _show_cad_inventory() -> None:
        state["view_mode"] = "cad"
        state["view_title"] = "CAD/BIM imports"
        state["view_note"] = "Read-only сверка CAD graph DB и CAD_BIM_Index: импорты, projection, слабые графы и дубли."
        if not state.get("cad_inventory"):
            _schedule(_load_cad_inventory())
        else:
            _render_view()

    def _ask_about_topic(topic: dict) -> None:
        dataset_id = str(state.get("selected_dataset") or "").strip()
        label = str(topic.get("label") or topic.get("id") or "").strip()
        if not dataset_id or not label:
            ui.notify("Сначала выберите датасет и тему", type="warning")
            return
        question = f"дай сводку по теме «{label}»"
        params = urlencode({"scope": f"ds:{dataset_id}", "question": question, "tab": "chat"})
        path = str(getattr(context.client.request, "url", "") or "")
        target_path = "/les/classic" if "/les/classic" in path else "/classic"
        ui.navigate.to(f"{target_path}?{params}")

    def _ask_about_dataset_project(row: dict | None = None) -> None:
        dataset_id = str((row or {}).get("id") or state.get("selected_dataset") or "").strip()
        dataset_name = str((row or {}).get("name") or state.get("view_title") or dataset_id).strip()
        if not dataset_id:
            ui.notify("Сначала выберите датасет", type="warning")
            return
        question = (
            f"прочитай проектный датасет «{dataset_name}»: что это за проект, "
            "какие тома/разделы/таблицы/чертежи видны, где искать ключевые данные и что не прочитано"
        )
        params = {"scope": f"ds:{dataset_id}", "question": question, "tab": "chat"}
        path = str(getattr(context.client.request, "url", "") or "")
        target_path = "/les/classic" if "/les/classic" in path else "/classic"
        ui.navigate.to(f"{target_path}?{urlencode(params)}")

    def _ask_about_file(file_name: str, role: str = "") -> None:
        dataset_id = str(state.get("selected_dataset") or "").strip()
        file_name = str(file_name or "").strip()
        if not dataset_id or not file_name:
            ui.notify("Сначала выберите датасет и файл", type="warning")
            return
        question = f"прочитай {role or 'этот PDF'} и дай инженерную сводку: что в нём есть, где искать ключевые данные, что не прочитано"
        params = {
            "scope": f"ds:{dataset_id}",
            "question": question,
            "target_file": file_name,
            "tab": "chat",
        }
        path = str(getattr(context.client.request, "url", "") or "")
        target_path = "/les/classic" if "/les/classic" in path else "/classic"
        ui.navigate.to(f"{target_path}?{urlencode(params)}")

    def _ask_about_cad_import(item: dict) -> None:
        source = str(item.get("source_basename") or item.get("source") or "").strip()
        import_id = str(item.get("id") or "").strip()
        docs = list(item.get("indexed_documents") or [])
        first_doc = docs[0] if docs and isinstance(docs[0], dict) else {}
        target_file = str(first_doc.get("file_name") or f"cad_bim_json_{import_id}.md").strip()
        dataset_id = str(first_doc.get("dataset_id") or "").strip()
        question = (
            f"что ты видишь в CAD/DWG источнике {source or import_id}? "
            f"Ответь по CAD/BIM projection {target_file}: какие элементы, слои, таблицы/спецификации видны, "
            "и честно скажи, что не прочитано."
        )
        params = {"question": question, "tab": "chat", "target_file": target_file}
        if dataset_id:
            params["scope"] = f"ds:{dataset_id}"
        path = str(getattr(context.client.request, "url", "") or "")
        target_path = "/les/classic" if "/les/classic" in path else "/classic"
        ui.navigate.to(f"{target_path}?{urlencode(params)}")

    def _open_cad_projection(item: dict) -> None:
        docs = list(item.get("indexed_documents") or [])
        first_doc = docs[0] if docs and isinstance(docs[0], dict) else {}
        doc_id = str(first_doc.get("id") or "").strip()
        if not doc_id:
            ui.notify("Projection не найден в CAD_BIM_Index", type="warning")
            return
        _schedule(_open_document(doc_id))

    def _show_fragments() -> None:
        state["view_mode"] = "fragments"
        _render_view()

    def _copy_sources() -> None:
        rows = state["hits"] or state["chunks"]
        if not rows:
            ui.notify("Нет выбранных частей документа для списка источников", type="warning")
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

    def _render_tool_result() -> None:
        result = state.get("tool_result") or {}
        if state.get("tool_running"):
            with ui.row().classes("items-center").style("gap:8px;margin-top:8px;"):
                ui.spinner(size="sm")
                _label("Выполняю tool dry-run…", size="11.5px", color="var(--dim)")
            return
        if not result:
            return
        status = str(result.get("status") or "")
        with ui.expansion(f"Результат диагностики · {status}", icon="o_account_tree").classes("w-full").props("dense").style(
            "border:1px solid var(--border);border-radius:8px;margin-top:8px;background:var(--bg);"
        ):
            with ui.row().classes("items-center").style("gap:6px;flex-wrap:wrap;padding:4px 8px;"):
                _badge(status, "tag-acc" if status == "ok" else "tag-warn")
                check = result.get("contract_check") if isinstance(result.get("contract_check"), dict) else {}
                _badge("проверено" if check.get("ok") else "есть замечания", "tag-acc" if check.get("ok") else "tag-warn")
                for warning in list(result.get("warnings") or [])[:3]:
                    _badge(str(warning)[:80], "tag-warn")
            preview = {
                "tool": result.get("tool"),
                "operation": result.get("operation"),
                "status": result.get("status"),
                "sources": result.get("sources"),
                "missing": result.get("missing"),
                "warnings": result.get("warnings"),
                "trace": result.get("trace"),
                "result": result.get("result"),
            }
            ui.code(json.dumps(preview, ensure_ascii=False, indent=2)[:12000]).style(
                "font-size:11px;white-space:pre-wrap;max-height:360px;overflow:auto;width:100%;"
            )

    def _render_status_error() -> None:
        err = last_api_error_text() or "proxy не вернул данные документов"
        add_log(f"[DOCS] {err}")
        ui.notify(err, type="negative")

    def _render_file_registry(memory: dict, project_pdf: dict) -> None:
        files = _source_map_files(memory, project_pdf)
        groups = _file_registry(files)
        with ui.expansion("Реестр файлов", icon="o_inventory_2", value=True).classes("w-full").props("dense").style(
            "border:1px solid var(--border);border-radius:8px;margin-top:12px;background:var(--bg-panel);"
        ):
            with ui.row().classes("items-center w-full").style("gap:7px;flex-wrap:wrap;padding:10px 12px 4px;"):
                _badge(f"{len(files)} файлов", "tag-acc" if files else "tag-dim")
                _badge(f"{len(groups)} групп")
                kind = _selected_dataset_kind()
                if kind:
                    _badge(_dataset_kind_label(kind), "tag-acc")
            if not groups:
                _label("Файлы появятся здесь после загрузки списка документов.", size="11.5px", color="var(--dim)").style(
                    "padding:4px 12px 12px;"
                )
                return
            for group in groups[:48]:
                samples = [name for name in (group.get("samples") or []) if name]
                with ui.element("div").style(
                    "border-top:1px solid var(--border);padding:8px 12px;background:var(--bg-panel);"
                ):
                    with ui.row().classes("items-center w-full").style("gap:6px;flex-wrap:wrap;"):
                        _badge(str(group.get("section") or "раздел"), "tag-acc")
                        _badge(str(group.get("role") or "тип"))
                        _badge(f"{int(group.get('files') or 0)} файлов")
                        if group.get("warnings"):
                            _badge(f"{int(group.get('warnings') or 0)} проверить", "tag-warn")
                    if samples:
                        _label("; ".join(_short_path(name, parts=4) for name in samples), size="11px", color="var(--dim)").style(
                            "margin-top:5px;overflow-wrap:anywhere;"
                        )
            if len(groups) > 48:
                _label(f"Показаны первые 48 групп из {len(groups)}.", size="11px", color="var(--dim)").style(
                    "padding:8px 12px 12px;"
                )

    def _render_dataset_kind_control() -> None:
        with ui.element("div").style(
            "border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-top:12px;"
            "background:var(--bg-panel);"
        ):
            with ui.row().classes("items-center w-full").style("gap:8px;flex-wrap:wrap;"):
                ui.icon("o_label").style("font-size:18px;color:var(--accent);")
                _label("Тип датасета", size="13px", weight=900)
                kind_select = ui.select(
                    DATASET_KIND_EDIT_OPTIONS,
                    value=_selected_dataset_kind(),
                ).props("dense outlined emit-value map-options").style(
                    "min-width:180px;background:var(--input-bg);"
                )
                kind_select.on("update:model-value", lambda e: _schedule(_save_dataset_kind(str(e.args or ""))))
                ui.element("div").style("flex:1;")
                ui.button(
                    "Спросить проект",
                    icon="o_chat",
                    on_click=lambda: _ask_about_dataset_project(_selected_dataset_row() or None),
                ).props("flat dense no-caps")
                ui.button(
                    "Обновить карту",
                    icon="o_refresh",
                    on_click=lambda: _schedule(_refresh_memory()),
                ).props("flat dense no-caps")

    def _render_project_source_map(memory: dict, project_pdf: dict, coverage: dict) -> None:
        files = _source_map_files(memory, project_pdf)
        selected = _selected_dataset_row()
        disciplines = [item for item in (project_pdf.get("discipline_summaries") or []) if isinstance(item, dict)]

        with ui.element("div").style(
            "border:1px solid var(--border);border-radius:8px;padding:12px 14px;margin-top:12px;"
            "background:var(--bg-panel);"
        ):
            with ui.row().classes("items-center w-full").style("gap:8px;flex-wrap:wrap;"):
                ui.icon("o_account_tree").style("font-size:19px;color:var(--accent);")
                _label("Л.И.С.Т. проекта", size="14px", weight=900)
                _label("локальный индекс структуры томов", size="11px", color="var(--dim)")
            with ui.row().classes("items-center").style("gap:6px;margin-top:9px;flex-wrap:wrap;"):
                _badge(str(selected.get("name") or state.get("selected_dataset") or "проект"), "tag-acc")
                _badge(f"{int(selected.get('document_count') or memory.get('document_count') or 0)} документов")
                _badge(f"{int(selected.get('chunk_count') or memory.get('chunk_count') or 0)} текстовых частей")
                if coverage:
                    read_count = int(coverage.get("files_ok") or coverage.get("files_extracted") or 0)
                    issue_count = int(coverage.get("extract_errors") or 0) + int(coverage.get("missing_source") or 0)
                    _badge(f"PDF {coverage.get('pdf_documents', 0)}")
                    _badge(f"прочитано {read_count}")
                    if issue_count:
                        _badge(f"проверить {issue_count}", "tag-warn")
            note = str(memory.get("reader_note") or "")
            if note:
                _label(note, size="11px", color="var(--dim)").style("margin-top:7px;")

        diagram = _dataset_structure_mermaid(memory, project_pdf, coverage, files)
        with ui.element("div").style(
            "border:1px solid var(--border);border-radius:8px;padding:12px 14px;margin-top:10px;"
            "background:var(--bg-panel);"
        ):
            with ui.row().classes("items-center w-full").style("gap:8px;flex-wrap:wrap;"):
                ui.icon("o_schema").style("font-size:18px;color:var(--accent);")
                _label("Структура Л.И.С.Т.", size="13px", weight=900)
                _label("как проект разложен для чтения", size="11px", color="var(--dim)")
            _label(
                "Схема показывает папки, разделы и найденные таблицы. По ней удобно выбрать том или сразу спросить проект.",
                size="11px",
                color="var(--dim)",
            ).style("margin-top:6px;")
            with ui.element("div").style(
                "margin-top:10px;border:1px solid var(--border);border-radius:8px;"
                "background:var(--bg);overflow:auto;padding:10px;min-height:260px;"
            ):
                ui.mermaid(diagram).classes("w-full").style("min-width:760px;")

        roots = _project_roots(files)
        if roots:
            _label("Проекты и папки", size="13px", weight=900).style("margin-top:14px;")
            with ui.row().classes("items-stretch w-full").style("gap:8px;flex-wrap:wrap;"):
                for root in roots[:8]:
                    roles = ", ".join(f"{k} {v}" for k, v in list((root.get("roles") or {}).items())[:3])
                    disciplines_text = ", ".join(f"{k} {v}" for k, v in list((root.get("disciplines") or {}).items())[:5])
                    with ui.element("div").style(
                        "border:1px solid var(--border);border-radius:8px;padding:10px 12px;"
                        "background:var(--bg-panel);min-width:220px;max-width:360px;flex:1;"
                    ):
                        _label(str(root.get("name") or "проект"), size="12.5px", weight=900).style(
                            "overflow-wrap:anywhere;"
                        )
                        with ui.row().classes("items-center").style("gap:5px;margin-top:6px;flex-wrap:wrap;"):
                            _badge(f"{root.get('files', 0)} PDF")
                            _badge(f"{root.get('ok', 0)} прочитано", "tag-acc")
                            if root.get("warnings"):
                                _badge(f"{root.get('warnings')} проверить", "tag-warn")
                        if disciplines_text:
                            _label(disciplines_text, size="11px", color="var(--dim)").style("margin-top:6px;")
                        if roles:
                            _label(roles, size="11px", color="var(--dim)").style("margin-top:3px;")

        if disciplines:
            _label("Разделы проекта", size="13px", weight=900).style("margin-top:14px;")
            with ui.row().classes("items-stretch w-full").style("gap:8px;flex-wrap:wrap;"):
                for item in disciplines[:18]:
                    roles = item.get("roles") if isinstance(item.get("roles"), dict) else {}
                    layers = item.get("layers") if isinstance(item.get("layers"), dict) else {}
                    role_text = ", ".join(f"{k} {v}" for k, v in list(roles.items())[:3])
                    layer_text = ", ".join(f"{k} {v}" for k, v in list(layers.items())[:3])
                    with ui.element("div").style(
                        "border:1px solid var(--border);border-radius:8px;padding:9px 11px;"
                        "background:var(--bg-panel);min-width:170px;max-width:280px;flex:1;"
                    ):
                        with ui.row().classes("items-center").style("gap:6px;flex-wrap:wrap;"):
                            _badge(str(item.get("discipline") or "PDF"), "tag-acc")
                            _badge(f"{int(item.get('files') or 0)} файлов")
                        if role_text:
                            _label(role_text, size="11px", color="var(--dim)").style("margin-top:6px;")
                        if layer_text:
                            _label(layer_text, size="11px", color="var(--dim)").style("margin-top:3px;")

        if files:
            _label("Файлы и тома", size="13px", weight=900).style("margin-top:14px;")
            with ui.row().classes("items-center w-full").style("gap:8px;flex-wrap:wrap;margin-top:7px;"):
                project_filter = ui.input(
                    value=state.get("project_filter") or "",
                    placeholder="поиск по файлам: шифр, раздел, название",
                ).props("dense outlined clearable").style("min-width:280px;flex:1;background:var(--input-bg);")
                project_filter.on(
                    "update:model-value",
                    lambda e: state.__setitem__("project_filter", str(e.args or "")),
                )
                project_filter.on("keydown.enter", lambda _e: _render_view())
                ui.button(icon="o_search", on_click=_render_view).props(
                    'flat dense round aria-label="Фильтровать Л.И.С.Т."'
                ).tooltip("Фильтровать список PDF / томов")
                _badge(f"{len(files)} файлов")
            needle = str(state.get("project_filter") or "").strip().lower()
            filtered: list[dict] = []
            for item in files:
                haystack = " ".join(
                    str(item.get(key) or "")
                    for key in ("file_name", "doc_role", "discipline", "cipher", "stage", "source_path", "status")
                ).lower()
                if not needle or needle in haystack:
                    filtered.append(item)
            if needle:
                _label(f"Найдено: {len(filtered)}", size="11px", color="var(--dim)").style("margin-top:6px;")
            for item in filtered[:90]:
                file_name = str(item.get("file_name") or "")
                doc_id = str(item.get("doc_id") or "")
                if not doc_id:
                    doc_id = str(_document_by_file_name(file_name).get("id") or "")
                role = str(item.get("doc_role") or "PDF")
                source_path = str(item.get("source_path") or "")
                layers = [str(x) for x in (item.get("layers") or []) if str(x)]
                warnings = [str(x) for x in (item.get("warnings") or []) if str(x)]
                status = str(item.get("status") or "")
                with ui.element("div").style(
                    "border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-top:8px;"
                    "background:var(--bg-panel);"
                ):
                    with ui.row().classes("items-center w-full").style("gap:6px;flex-wrap:wrap;"):
                        _badge(role, "tag-acc" if status == "ok" else "tag-warn")
                        if item.get("discipline"):
                            _badge(str(item.get("discipline")))
                        if item.get("cipher"):
                            _badge(str(item.get("cipher")))
                        if layers:
                            _badge(" · ".join(layers[:3]), "tag-dim")
                        _label(file_name.rsplit("/", 1)[-1], size="12px", weight=900).style(
                            "flex:1;min-width:220px;overflow-wrap:anywhere;"
                        )
                        if doc_id:
                            ui.button(
                                icon="o_article",
                                on_click=lambda value=doc_id: _schedule(_open_document(value)),
                            ).props('flat dense round aria-label="Открыть в LES"').tooltip("Открыть во встроенном просмотре LES")
                            ui.button(
                                icon="o_open_in_new",
                                on_click=lambda name=file_name, value=doc_id: _schedule(_open_native_file_name(name, value)),
                            ).props('flat dense round aria-label="Открыть системно"').tooltip("Открыть исходный файл системно")
                        ui.button(
                            icon="o_chat",
                            on_click=lambda name=file_name, r=role: _ask_about_file(name, r),
                        ).props('flat dense round aria-label="Спросить по файлу"').tooltip("Спросить модель по этому файлу")
                    _label(_short_path(file_name, parts=5), size="11px", color="var(--dim)").style("margin-top:5px;overflow-wrap:anywhere;")
                    if warnings:
                        _label("Проверить: " + "; ".join(warnings[:3]), size="10.5px", color="var(--warn)").style("margin-top:4px;overflow-wrap:anywhere;")
            if len(filtered) > 90:
                _label(f"Показаны первые 90 из {len(filtered)}. Уточните фильтр.", size="11px", color="var(--dim)").style("margin-top:8px;")

    def _render_datasets() -> None:
        panel = refs.get("datasets")
        if panel is None:
            return
        panel.clear()
        with panel:
            if not state["datasets"]:
                _label("Датасетов не найдено", color="var(--dim)")
                return
            kind_filter = str(state.get("dataset_kind_filter") or "")
            rows = [
                row for row in state["datasets"]
                if not kind_filter or str(row.get("dataset_kind") or "") == kind_filter
            ]
            if not rows:
                _label("Датасетов с такой меткой нет", color="var(--dim)")
                return
            for row in rows:
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
                        if row.get("dataset_kind_label"):
                            _badge(str(row.get("dataset_kind_label")), "tag-acc")
                        status_ready = str(row.get("status", "")).upper() in {"IDLE", "INDEXED"}
                        _badge("готов" if status_ready else "читается", "tag-acc" if status_ready else "tag-dim")
                        _badge(f"{int(row.get('document_count') or 0)} док.")
                        pending = int(row.get("pending_count") or 0)
                        errors = int(row.get("error_count") or 0)
                        missing = int(row.get("missing_count") or 0)
                        if pending:
                            _badge(f"{pending} ждёт", "tag-warn")
                        if errors:
                            _badge(f"{errors} ошибок", "tag-err")
                        if missing:
                            _badge(f"{missing} пропало", "tag-err")
                        _badge(f"{int(row.get('chunk_count') or 0)} частей")

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
                        indexed = str(row.get("status", "")).upper() == "INDEXED"
                        _badge("готов" if indexed else "проверить", "tag-acc" if indexed else "tag-warn")
                        if row.get("content_type"):
                            _badge(str(row.get("content_type")).upper())
                        _badge(f"{int(row.get('chunk_count') or 0)} частей")
                        _badge(_format_size(row.get("file_size")))
                    if row.get("last_error"):
                        _label(str(row["last_error"])[:180], size="11px", color="var(--err)")

    def _render_map() -> None:
        memory = state.get("dataset_memory") or {}
        if state.get("memory_loading"):
            with ui.element("div").style(
                "border:1px solid var(--border);border-radius:8px;padding:18px;margin-top:12px;"
            ):
                with ui.row().classes("items-center").style("gap:8px;"):
                    ui.spinner(size="sm")
                    _label("Собираю карту датасета…", color="var(--dim)")
            return
        if not state["selected_dataset"]:
            with ui.element("div").style(
                "border:1px dashed var(--border);border-radius:8px;padding:18px;margin-top:12px;"
            ):
                _label("Выберите датасет слева — покажу карту слоёв и маршрутов.", color="var(--dim)")
            return
        if not memory:
            with ui.element("div").style(
                "border:1px dashed var(--border);border-radius:8px;padding:18px;margin-top:12px;"
            ):
                _label("Карта ещё не загружена. Нажмите обновить память датасета.", color="var(--dim)")
            return

        graph = memory.get("source_graph") if isinstance(memory.get("source_graph"), dict) else {}
        topic_map = memory.get("topic_map") if isinstance(memory.get("topic_map"), dict) else {}
        section_map = memory.get("section_map") if isinstance(memory.get("section_map"), dict) else {}
        source_layers = list(memory.get("source_layers") or [])
        routes = list(memory.get("retrieval_routes") or [])
        gaps = list(memory.get("known_gaps") or [])
        topics = list(topic_map.get("topics") or [])
        section_files = list(section_map.get("files") or [])
        top_files_by_layer = graph.get("top_files_by_layer") if isinstance(graph, dict) else {}

        project_pdf = state.get("pdf_extract") if isinstance(state.get("pdf_extract"), dict) else {}
        if not project_pdf:
            project_pdf = memory.get("project_pdf_extract") if isinstance(memory.get("project_pdf_extract"), dict) else {}
        coverage = project_pdf.get("coverage") if isinstance(project_pdf.get("coverage"), dict) else {}
        _render_dataset_kind_control()
        _render_file_registry(memory, project_pdf)
        _render_project_source_map(memory, project_pdf, coverage)
        with ui.element("div").style(
            "border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-top:12px;"
            "background:var(--bg-panel);"
        ):
            with ui.row().classes("items-center w-full").style("gap:7px;flex-wrap:wrap;"):
                ui.icon("o_picture_as_pdf").style("font-size:18px;color:var(--accent);")
                _label("Чтение PDF", size="13px", weight=900)
                _label("обновить карту томов, таблиц и листов", size="11px", color="var(--dim)")
                if state.get("pdf_extract_loading"):
                    ui.spinner(size="sm")
                ui.element("div").style("flex:1;")
                ui.button(
                    "Обновить",
                    icon="o_refresh",
                    on_click=lambda: _schedule(_load_pdf_extract_summary()),
                ).props("flat dense no-caps")
                ui.button(
                    "Перечитать",
                    icon="o_play_arrow",
                    on_click=lambda: _schedule(_run_pdf_extract()),
                ).props("flat dense no-caps")
            if coverage:
                with ui.row().classes("items-center").style("gap:5px;margin-top:8px;flex-wrap:wrap;"):
                    read_count = int(coverage.get("files_ok") or coverage.get("files_extracted") or 0)
                    _badge(f"PDF: {coverage.get('pdf_documents', 0)}", "tag-dim")
                    _badge(f"Прочитано: {read_count}", "tag-dim")
                    for title, key in (("ПЗ", "pz_files"), ("ВОР", "vor_files"), ("СО", "so_files")):
                        if key in coverage:
                            _badge(f"{title}: {coverage.get(key)}", "tag-dim")
                    for title, key in (("Ошибка", "extract_errors"), ("Нет файла", "missing_source")):
                        if coverage.get(key):
                            _badge(f"{title}: {coverage.get(key)}", "tag-warn")
            warnings = [str(x) for x in (project_pdf.get("warnings") or []) if str(x).strip()]
            if warnings:
                _label("Что проверить: " + "; ".join(warnings[:4]), size="11px", color="var(--warn)").style(
                    "margin-top:7px;overflow-wrap:anywhere;"
                )
            if project_pdf.get("warnings_truncated"):
                _label(
                    f"Показаны не все предупреждения: {int(project_pdf.get('warnings_total') or len(warnings))} всего.",
                    size="11px",
                    color="var(--warn)",
                ).style("margin-top:5px;")
            nav = [item for item in (project_pdf.get("source_navigation") or []) if isinstance(item, dict)]
            for item in nav[:6]:
                file_name = str(item.get("file_name") or "")
                role = str(item.get("role") or item.get("doc_role") or "PDF")
                with ui.row().classes("items-center w-full").style("gap:6px;margin-top:7px;flex-wrap:wrap;"):
                    _badge(role, "tag-acc")
                    _label(file_name, size="11.5px").style(
                        "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:160px;"
                    )
                    if file_name:
                        ui.button(
                            "Спросить",
                            icon="o_chat",
                            on_click=lambda name=file_name, r=role: _ask_about_file(name, r),
                        ).props("flat dense no-caps")

        if topics:
            _label("Темы датасета", size="13px", weight=900).style("margin-top:18px;")
            for topic in topics[:12]:
                topic_label = str(topic.get("label") or topic.get("id") or "тема")
                top_files = list(topic.get("top_files") or [])
                top_sections = list(topic.get("top_sections") or [])
                aliases = ", ".join(str(x) for x in (topic.get("query_aliases") or [])[:8])
                with ui.element("div").style(
                    "border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-top:8px;"
                    "background:var(--bg-panel);"
                ):
                    with ui.row().classes("items-center w-full").style("gap:7px;flex-wrap:wrap;"):
                        _badge(topic_label, "tag-acc")
                        _badge(f"{len(top_files)} файлов")
                        _badge(f"{len(top_sections)} разделов")
                        ui.element("div").style("flex:1;")
                        ui.button(
                            "Спросить по теме",
                            icon="o_chat",
                            on_click=lambda t=topic: _ask_about_topic(t),
                        ).props("flat dense no-caps")
                    if aliases:
                        _label(f"Синонимы: {aliases}", size="11px", color="var(--dim)").style("margin-top:5px;")
                    for file in top_files[:4]:
                        _label(
                            f"• {file.get('file_name')} · {file.get('role') or 'документ'} · {int(file.get('chunk_count') or 0)} частей",
                            size="11.5px",
                        ).style("margin-top:5px;overflow-wrap:anywhere;")
                    for section in top_sections[:4]:
                        _label(
                            f"§ {section.get('heading')} · {section.get('file_name')}",
                            size="11.5px",
                            color="var(--dim)",
                        ).style("margin-top:4px;overflow-wrap:anywhere;")

        with ui.element("div").style(
            "border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-top:12px;"
            "background:var(--bg-panel);"
        ):
            with ui.row().classes("items-center w-full").style("gap:8px;"):
                ui.icon("o_edit_note").style("font-size:18px;color:var(--accent);")
                _label("Заметка к проекту", size="13px", weight=900)
                _label("что важно учитывать при чтении", size="11px", color="var(--dim)")
                ui.element("div").style("flex:1;")
                ui.button("Сохранить", icon="o_save", on_click=lambda: _schedule(_save_guidance())).props(
                    "flat dense no-caps"
                )
            guidance_input = ui.textarea(
                value=state.get("operator_guidance") or "",
                placeholder=(
                    "Например: это рабочая ПД по котельной; актуальные данные брать из ПЗ и ВОР, "
                    "старые КП использовать только как ориентир."
                ),
            ).props("outlined autogrow clearable").style(
                "width:100%;margin-top:8px;min-height:74px;background:var(--input-bg);"
            )
            guidance_input.on("update:model-value", lambda e: state.__setitem__("operator_guidance", str(e.args or "")))

        if source_layers:
            _label("Слои данных", size="13px", weight=900).style("margin-top:18px;")
            for layer in source_layers:
                with ui.element("div").style(
                    "border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-top:8px;"
                    "background:var(--bg-panel);"
                ):
                    with ui.row().classes("items-center").style("gap:7px;flex-wrap:wrap;"):
                        _badge(str(layer.get("label") or layer.get("id")), "tag-acc")
                        _badge(f"{int(layer.get('files') or 0)} файлов")
                        _label(str(layer.get("role") or ""), size="12px", weight=800).style("flex:1;min-width:220px;")
                    _label("Когда полезно: " + str(layer.get("use_for") or "выбор источника"), size="11.5px", color="var(--dim)").style("margin-top:5px;")
                    _label("Как сверять: " + str(layer.get("evidence_rule") or "утверждения подтверждать источником"), size="11.5px", color="var(--dim)").style("margin-top:3px;")

        if routes:
            _label("Маршруты чтения", size="13px", weight=900).style("margin-top:18px;")
            for route in routes:
                files = list(route.get("target_files") or [])
                with ui.element("div").style(
                    "border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-top:8px;"
                    "background:var(--bg-panel);"
                ):
                    _label(str(route.get("when") or route.get("id") or "маршрут"), size="12.5px", weight=900)
                    _label(str(route.get("method") or ""), size="11.5px", color="var(--dim)").style("margin-top:4px;")
                    layers = ", ".join(str(x) for x in (route.get("prefer_layers") or [])[:6])
                    if layers:
                        _label(f"Слои: {layers}", size="11px", color="var(--dim)").style("margin-top:3px;")
                    if files:
                        with ui.column().classes("w-full gap-1").style("margin-top:7px;"):
                            for file in files[:5]:
                                _label(
                                    f"• {file.get('file_name')} · {file.get('role') or 'документ'} · {int(file.get('chunk_count') or 0)} частей",
                                    size="11.5px",
                                ).style("overflow-wrap:anywhere;")

        if isinstance(top_files_by_layer, dict) and top_files_by_layer:
            _label("Первые файлы по слоям", size="13px", weight=900).style("margin-top:18px;")
            for layer_id, files in list(top_files_by_layer.items())[:8]:
                with ui.expansion(str(layer_id), icon="o_account_tree").classes("w-full").props("dense").style(
                    "border:1px solid var(--border);border-radius:8px;margin-top:7px;background:var(--bg-panel);"
                ):
                    for file in list(files or [])[:8]:
                        _label(
                            f"{file.get('file_name')} · {file.get('role') or 'документ'} · {int(file.get('chunk_count') or 0)} частей",
                            size="11.5px",
                        ).style("padding:4px 8px;overflow-wrap:anywhere;")

        if section_files:
            _label("Разделы внутри файлов", size="13px", weight=900).style("margin-top:18px;")
            for file in section_files[:14]:
                file_name = str(file.get("file_name") or "")
                sections = list(file.get("sections") or [])
                if not file_name or not sections:
                    continue
                with ui.expansion(file_name.rsplit("/", 1)[-1], icon="o_format_list_bulleted").classes("w-full").props("dense").style(
                    "border:1px solid var(--border);border-radius:8px;margin-top:7px;background:var(--bg-panel);"
                ):
                    _label(file_name, size="11px", color="var(--dim)").style("padding:4px 8px;overflow-wrap:anywhere;")
                    for section in sections[:10]:
                        hints = ", ".join(str(x) for x in (section.get("topic_hints") or [])[:4])
                        suffix = f" · {hints}" if hints else ""
                        _label(
                            f"§ {section.get('heading')} · {int(section.get('chunk_count') or 0)} частей{suffix}",
                            size="11.5px",
                        ).style("padding:4px 8px;overflow-wrap:anywhere;")

        if gaps:
            _label("Ограничения карты", size="13px", weight=900).style("margin-top:18px;")
            for gap in gaps:
                with ui.row().classes("items-center").style("gap:6px;margin-top:5px;"):
                    ui.icon("o_info").style("font-size:15px;color:var(--warn);")
                    _label(str(gap), size="11.5px", color="var(--dim)")

    def _render_cad_inventory() -> None:
        if state.get("cad_loading"):
            with ui.element("div").style(
                "border:1px solid var(--border);border-radius:8px;padding:18px;margin-top:12px;"
            ):
                with ui.row().classes("items-center").style("gap:8px;"):
                    ui.spinner(size="sm")
                    _label("Читаю CAD/BIM inventory…", color="var(--dim)")
            return
        data = state.get("cad_inventory") if isinstance(state.get("cad_inventory"), dict) else {}
        if not data:
            with ui.element("div").style(
                "border:1px dashed var(--border);border-radius:8px;padding:18px;margin-top:12px;"
            ):
                _label("CAD inventory ещё не загружен.", color="var(--dim)")
                ui.button("Загрузить CAD", icon="o_architecture", on_click=lambda: _schedule(_load_cad_inventory())).props(
                    "flat dense no-caps"
                ).style("margin-top:8px;")
            return

        totals = data.get("totals") if isinstance(data.get("totals"), dict) else {}
        imports = list(data.get("imports") or [])
        duplicate_groups = list(data.get("duplicate_groups") or [])
        weak = [item for item in imports if item.get("quality_status") != "ok"]
        duplicate_indexed = [item for item in imports if item.get("projection_index_status") == "duplicate_indexed"]
        not_indexed = [item for item in imports if item.get("projection_index_status") == "not_indexed"]

        with ui.row().classes("items-stretch w-full").style("gap:8px;flex-wrap:wrap;margin-top:12px;"):
            metrics = [
                ("Imports", totals.get("imports", 0)),
                ("Elements", totals.get("elements", 0)),
                ("Projection docs", totals.get("projection_documents", 0)),
                ("Weak", totals.get("weak_imports", 0)),
                ("Duplicate groups", totals.get("duplicate_groups", 0)),
                ("Dup indexed", totals.get("duplicate_indexed_imports", 0)),
            ]
            for title, value in metrics:
                with ui.element("div").style(
                    "border:1px solid var(--border);border-radius:8px;padding:10px 12px;"
                    "min-width:120px;background:var(--bg-panel);"
                ):
                    _label(str(value), size="17px", weight=900)
                    _label(title, size="11px", color="var(--dim)")

        with ui.row().classes("items-center").style("gap:6px;margin-top:12px;flex-wrap:wrap;"):
            _badge("read-only", "tag-acc")
            _badge(str(data.get("db_path") or "cad_bim_graph.db"))
            _badge(str(data.get("meta_db_path") or "les_meta_qwen.db"))
            ui.element("div").style("flex:1;")
            ui.button("Обновить CAD", icon="o_refresh", on_click=lambda: _schedule(_load_cad_inventory())).props(
                "flat dense no-caps"
            )

        if duplicate_indexed:
            _label("Projection индексирован несколько раз", size="13px", weight=900).style("margin-top:18px;")
            for item in duplicate_indexed[:8]:
                docs = list(item.get("indexed_documents") or [])
                with ui.element("div").style(
                    "border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-top:8px;"
                    "background:var(--bg-panel);"
                ):
                    with ui.row().classes("items-center w-full").style("gap:7px;flex-wrap:wrap;"):
                        _badge(str(item.get("id") or ""), "tag-warn")
                        _badge(f"{len(docs)} docs", "tag-warn")
                        _label(str(item.get("source_basename") or item.get("source") or ""), size="12px", weight=800).style(
                            "flex:1;min-width:220px;overflow-wrap:anywhere;"
                        )
                        ui.button("Открыть", icon="o_article", on_click=lambda x=item: _open_cad_projection(x)).props(
                            "flat dense no-caps"
                        )
                        ui.button("Спросить", icon="o_chat", on_click=lambda x=item: _ask_about_cad_import(x)).props(
                            "flat dense no-caps"
                        )
                    for doc in docs[:6]:
                        _label(
                            f"• {doc.get('file_name')} · {int(doc.get('chunk_count') or 0)} частей",
                            size="11.5px",
                            color="var(--dim)",
                        ).style("margin-top:4px;overflow-wrap:anywhere;")

        if duplicate_groups:
            _label("Дубли импортов", size="13px", weight=900).style("margin-top:18px;")
            for group in duplicate_groups[:10]:
                with ui.expansion(
                    f"{group.get('count')} × {group.get('source_fingerprint')}",
                    icon="o_content_copy",
                ).classes("w-full").props("dense").style(
                    "border:1px solid var(--border);border-radius:8px;margin-top:7px;background:var(--bg-panel);"
                ):
                    _label(
                        f"elements={group.get('element_count')} · relations={group.get('relation_count')} · properties={group.get('property_count')}",
                        size="11px",
                        color="var(--dim)",
                    ).style("padding:4px 8px;")
                    for import_id, source in zip(group.get("import_ids") or [], group.get("sources") or []):
                        _label(f"• {import_id} · {source}", size="11.5px").style(
                            "padding:4px 8px;overflow-wrap:anywhere;"
                        )

        if weak:
            _label("Слабые импорты", size="13px", weight=900).style("margin-top:18px;")
            for item in weak[:20]:
                with ui.element("div").style(
                    "border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-top:8px;"
                    "background:var(--bg-panel);"
                ):
                    with ui.row().classes("items-center w-full").style("gap:7px;flex-wrap:wrap;"):
                        _badge(str(item.get("quality_status") or ""), "tag-warn")
                        _badge(str(item.get("projection_index_status") or ""))
                        _badge(f"{int(item.get('element_count') or 0)} el")
                        _badge(f"{int(item.get('relation_count') or 0)} rel")
                        _label(str(item.get("source_basename") or item.get("source") or ""), size="12px", weight=800).style(
                            "flex:1;min-width:220px;overflow-wrap:anywhere;"
                        )
                        ui.button("Открыть", icon="o_article", on_click=lambda x=item: _open_cad_projection(x)).props(
                            "flat dense no-caps"
                        )
                        ui.button("Спросить", icon="o_chat", on_click=lambda x=item: _ask_about_cad_import(x)).props(
                            "flat dense no-caps"
                        )

        if not_indexed:
            _label("Импорты без projection в индексе", size="13px", weight=900).style("margin-top:18px;")
            for item in not_indexed[:20]:
                _label(
                    f"• {item.get('id')} · {item.get('source_basename') or item.get('source')}",
                    size="11.5px",
                    color="var(--err)",
                ).style("margin-top:4px;overflow-wrap:anywhere;")

        _label("Все CAD/BIM imports", size="13px", weight=900).style("margin-top:18px;")
        for item in imports[:80]:
            status_cls = "tag-acc" if item.get("quality_status") == "ok" else "tag-warn"
            with ui.element("div").style(
                "border-bottom:1px solid var(--border);padding:9px 0;"
            ):
                with ui.row().classes("items-center w-full").style("gap:6px;flex-wrap:wrap;"):
                    _badge(str(item.get("id") or ""), status_cls)
                    _badge(str(item.get("quality_status") or ""), status_cls)
                    _badge(str(item.get("projection_index_status") or ""))
                    _badge(f"{int(item.get('element_count') or 0)} el")
                    _badge(f"{int(item.get('indexed_count') or 0)} indexed")
                    _label(str(item.get("source_basename") or item.get("source") or ""), size="11.5px", weight=800).style(
                        "flex:1;min-width:260px;overflow-wrap:anywhere;"
                    )
                    ui.button(icon="o_article", on_click=lambda x=item: _open_cad_projection(x)).props(
                        'flat dense round aria-label="Открыть CAD projection"'
                    ).tooltip("Открыть projection в документах")
                    ui.button(icon="o_chat", on_click=lambda x=item: _ask_about_cad_import(x)).props(
                        'flat dense round aria-label="Спросить по CAD"'
                    ).tooltip("Спросить модель по этому CAD projection")

    def _render_fragments() -> None:
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
                    _badge(f"часть {item.get('chunk_ord')}", "tag-acc")
                    if item.get("rank"):
                        _badge(f"совпадение {item.get('rank')}")
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
                ui.button("Текст", icon="o_article", on_click=_show_fragments).props(
                    "flat dense no-caps"
                ).classes("tag-acc" if state["view_mode"] == "fragments" else "")
                ui.button("CAD", icon="o_architecture", on_click=_show_cad_inventory).props(
                    "flat dense no-caps"
                ).classes("tag-acc" if state["view_mode"] == "cad" else "")
                ui.button("Карта", icon="o_hub", on_click=_show_map).props(
                    "flat dense no-caps"
                ).classes("tag-acc" if state["view_mode"] == "map" else "")
                ui.button(icon="o_refresh", on_click=lambda: _schedule(_refresh_memory())).props(
                    'flat dense round aria-label="Обновить карту датасета"'
                ).tooltip("Пересобрать typed memory / карту датасета")
                ui.button(icon="o_content_copy", on_click=_copy_sources).props(
                    'flat dense round aria-label="Скопировать источники"'
                ).tooltip("Скопировать список источников")
            _label(state["view_note"], size="11.5px", color="var(--dim)")
            if state["view_mode"] == "map":
                _render_map()
            elif state["view_mode"] == "cad":
                _render_cad_inventory()
            else:
                _render_fragments()

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
            _label("Л.И.С.Т.: карта проекта, файлы и вопросы по источникам", size="11.5px", color="var(--dim)")
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
                kind_filter = ui.select(
                    DATASET_KIND_OPTIONS,
                    value=state.get("dataset_kind_filter") or "",
                ).props("dense outlined emit-value map-options").style("width:100%;background:var(--input-bg);")
                kind_filter.on(
                    "update:model-value",
                    lambda e: (state.__setitem__("dataset_kind_filter", str(e.args or "")), _render_datasets()),
                )
                dataset_filter = ui.input(placeholder="фильтр").props("dense outlined clearable").style("width:100%;")
                dataset_filter.on(
                    "update:model-value",
                    lambda e: (state.__setitem__("dataset_filter", str(e.args or "")), _render_datasets()),
                )
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
