"""No-AI document browser for LES datasets.

This page is an operator surface: dataset -> document -> chunks/search. It
does not ask the model anything; it makes the indexed corpus visible.
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import json
import re
from urllib.parse import quote, urlencode

from nicegui import context, ui

from sovushka.state import api_get, api_get_bytes, api_patch, api_post, api_post_file, add_log, last_api_error_text

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
DATASET_GROUP_OPTIONS = {
    "": "Все",
    "project": "Проекты",
    "other": "Не проекты",
}


def build_documents(*, surface: str = "documents") -> None:
    if surface not in {"documents", "studio", "cad_bim"}:
        raise ValueError(f"Unknown documents surface: {surface}")
    initial_mode = {"documents": "map", "studio": "studio", "cad_bim": "cad"}[surface]
    initial_title = {
        "documents": "Выберите файл",
        "studio": "Студия документов",
        "cad_bim": "CAD/BIM",
    }[surface]
    initial_note = {
        "documents": "Выберите файл: покажем только извлечённое содержимое и оригинал.",
        "studio": "Черновики DOCX/XLSX по выбранным источникам с обязательной проверкой.",
        "cad_bim": "Отдельный контур моделей и их проекций.",
    }[surface]
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
        "pdf_contour": {},
        "pdf_contour_loading": False,
        "pdf_contour_preview": "",
        "pdf_contour_preview_loading": False,
        "pdf_contour_page": 0,
        "cad_inventory": {},
        "cad_loading": False,
        "view_mode": initial_mode,
        "selected_dataset": "",
        "selected_doc_id": "",
        "selected_doc_name": "",
        "selected_doc_ids": [],
        "dataset_filter": "",
        "dataset_kind_filter": "",
        "dataset_group_filter": "",
        "document_filter": "",
        "document_folder_filter": "",
        "document_extension_filter": "",
        "document_status_filter": "",
        "document_role_filter": "",
        "document_tree_open": [],
        "document_map_files": [],
        "document_map_label": "",
        "project_filter": "",
        "composition_view": "tree",
        "selected_folder": "",
        "composition_folder_filter": "",
        "composition_extension_filter": "",
        "composition_status_filter": "",
        "composition_role_filter": "",
        "composition_name_filter": "",
        "composition_file": {},
        "composition_file_loading": False,
        "map_target": "dataset",
        "dataset_index_brief": {},
        "dataset_index_brief_loading": False,
        "rag_readiness": {},
        "rag_readiness_loading": False,
        "dataset_integrity": {},
        "dataset_integrity_loading": False,
        "dataset_index_quality": {},
        "dataset_index_quality_loading": False,
        "office_forms": [],
        "office_projects": [],
        "office_artifacts": [],
        "office_form_id": "",
        "office_project_id": "",
        "office_format": "docx",
        "office_fields": [],
        "office_manual": {},
        "office_preview": "",
        "office_instruction": "",
        "office_agent_ir": {},
        "office_agent_running": False,
        "office_agent_applied": False,
        "office_review_confirmed": False,
        "office_loading": False,
        "office_creating": False,
        "query": "",
        "view_title": initial_title,
        "view_note": initial_note,
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
        name = str(row.get("display_name") or row.get("name") or row.get("id") or "")
        return name or "Без названия"

    def _is_system_dataset(row: dict | None = None) -> bool:
        target = row or _selected_dataset_row()
        return str((target or {}).get("dataset_scope") or "user") == "system"

    def _file_icon(file_name: str) -> str:
        suffix = str(file_name or "").lower().rsplit(".", 1)[-1]
        return {
            "pdf": "o_picture_as_pdf",
            "doc": "o_description",
            "docx": "o_description",
            "xls": "o_table_view",
            "xlsx": "o_table_view",
            "csv": "o_table_view",
            "dwg": "o_architecture",
            "dxf": "o_architecture",
            "ifc": "o_view_in_ar",
            "rvt": "o_view_in_ar",
            "msg": "o_mail",
            "eml": "o_mail",
        }.get(suffix, "o_draft")

    def _file_kind(file_name: str) -> str:
        parts = str(file_name or "").rsplit(".", 1)
        return parts[-1].upper() if len(parts) > 1 else "Файл"

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

    def _dataset_group(row: dict) -> str:
        kind = str(row.get("dataset_kind") or "").strip()
        if kind:
            return "project" if kind == "project" else "other"
        name = str(row.get("name") or row.get("id") or "").strip().upper()
        non_project_prefixes = (
            "ARTEL", "BOOKS", "CAD_BIM", "DOCS_OTHER", "EXPORTS", "GESN_", "GKRF",
            "MAIL", "NTD_", "SMETA_", "КАТАЛОГ",
        )
        return "other" if name.startswith(non_project_prefixes) else "project"

    def _file_sort_key(item: dict) -> tuple[bool, str]:
        file_name = str(item.get("file_name") or "")
        basename = file_name.rsplit("/", 1)[-1]
        technical = basename.startswith(".") or basename.startswith("_les_")
        return technical, file_name.casefold()

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
        return sorted(result, key=_file_sort_key)

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

    def _composition_files(memory: dict, project_pdf: dict) -> list[dict]:
        """Full dataset inventory enriched by LIST metadata when available."""
        list_files = _source_map_files(memory, project_pdf)
        list_by_name = {str(item.get("file_name") or ""): item for item in list_files}
        result: list[dict] = []
        seen: set[str] = set()
        for row in state.get("documents") or []:
            file_name = str(row.get("file_name") or "")
            enriched = {
                "file_name": file_name,
                "doc_id": str(row.get("id") or ""),
                "status": str(row.get("status") or ""),
                "file_size": row.get("file_size"),
                "doc_type": str(row.get("doc_type") or row.get("content_type") or ""),
                **dict(list_by_name.get(file_name) or {}),
            }
            result.append(enriched)
            seen.add(file_name)
        for item in list_files:
            file_name = str(item.get("file_name") or "")
            if file_name not in seen:
                result.append(dict(item))
        return result

    def _set_composition_view(view: str) -> None:
        state["composition_view"] = view if view in {"tree", "grid", "list", "table"} else "tree"
        _render_view()

    def _remember_document_tree_folder(path: str, opened: bool) -> None:
        current = {str(item) for item in (state.get("document_tree_open") or []) if str(item)}
        if opened:
            current.add(path)
        else:
            current.discard(path)
        state["document_tree_open"] = sorted(current)

    def _focus_document_folder(path: str) -> None:
        normalized = str(path or "").strip("/")
        state["document_filter"] = ""
        state["document_map_files"] = []
        state["document_map_label"] = ""
        state["document_tree_open"] = [
            "/".join(normalized.split("/")[:index])
            for index in range(1, len(normalized.split("/")) + 1)
            if normalized
        ]
        document_filter = refs.get("document_filter")
        if document_filter is not None:
            document_filter.set_value("")
        _render_documents()

    def _filter_documents_from_map(value: str) -> None:
        query = str(value or "").strip()
        memory = state.get("dataset_memory") if isinstance(state.get("dataset_memory"), dict) else {}
        project_pdf = state.get("pdf_extract") if isinstance(state.get("pdf_extract"), dict) else {}
        if not project_pdf and isinstance(memory, dict):
            project_pdf = memory.get("project_pdf_extract") if isinstance(memory.get("project_pdf_extract"), dict) else {}
        matches = (
            [
                str(item.get("file_name") or "")
                for item in _composition_files(memory, project_pdf)
                if str(item.get("discipline") or "").strip() == query
            ]
            if query
            else []
        )
        state["document_filter"] = ""
        state["document_map_files"] = matches
        state["document_map_label"] = query
        _render_documents()

    def _set_document_text_filter(value: str) -> None:
        state["document_filter"] = str(value or "")
        state["document_map_files"] = []
        state["document_map_label"] = ""
        _render_documents()

    def _set_document_file_filter(key: str, value: str) -> None:
        state[key] = str(value or "")
        state["document_map_files"] = []
        state["document_map_label"] = ""
        _render_documents()

    def _select_composition_folder(folder: str) -> None:
        state["selected_folder"] = str(folder or "")
        _render_view()

    def _set_composition_filter(key: str, value: str) -> None:
        state[key] = str(value or "")
        state["selected_folder"] = ""
        _render_view()

    async def _inspect_composition_file(doc_id: str, file_name: str) -> None:
        if not doc_id:
            return
        state["view_mode"] = "map"
        state["map_target"] = "file"
        state["view_title"] = _dataset_title(_selected_dataset_row())
        state["view_note"] = "Извлечённое содержимое файла и оригинал."
        state["composition_file_loading"] = True
        state["pdf_contour"] = {}
        state["pdf_contour_loading"] = file_name.lower().endswith(".pdf")
        state["pdf_contour_preview"] = ""
        state["pdf_contour_preview_loading"] = False
        state["pdf_contour_page"] = 0
        state["composition_file"] = {"doc_id": doc_id, "file_name": file_name}
        _render_documents()
        _render_view()
        chunks_request = api_get(
            f"/api/documents/by-id/{quote(doc_id, safe='')}/chunks?"
            + urlencode({"limit": 12, "max_chars": 1800})
        )
        contour_request = (
            api_get(f"/api/documents/by-id/{quote(doc_id, safe='')}/pdf-contour?max_pages=80")
            if file_name.lower().endswith(".pdf")
            else asyncio.sleep(0, result={})
        )
        data, contour = await asyncio.gather(chunks_request, contour_request)
        state["composition_file_loading"] = False
        state["pdf_contour_loading"] = False
        if not isinstance(data, dict):
            _render_status_error()
            _render_view()
            return
        state["composition_file"] = {
            "doc_id": doc_id,
            "file_name": file_name,
            "document": dict(data.get("document") or {}),
            "chunks": list(data.get("chunks") or []),
            "total": int(data.get("total") or 0),
        }
        state["pdf_contour"] = contour if isinstance(contour, dict) else {}
        _render_documents()
        _render_view()
        pages = list((state.get("pdf_contour") or {}).get("pages") or [])
        if pages:
            await _load_pdf_contour_preview(int(pages[0].get("page") or 1))

    async def _load_pdf_contour_preview(page_number: int) -> None:
        file_data = state.get("composition_file") or {}
        doc_id = str(file_data.get("doc_id") or "")
        if not doc_id or page_number < 1:
            return
        state["pdf_contour_page"] = page_number
        state["pdf_contour_preview_loading"] = True
        state["pdf_contour_preview"] = ""
        _render_view()
        result = await api_get_bytes(
            f"/api/documents/by-id/{quote(doc_id, safe='')}/pdf-contour/pages/{page_number}/preview?width=1100"
        )
        if doc_id != str((state.get("composition_file") or {}).get("doc_id") or ""):
            return
        state["pdf_contour_preview_loading"] = False
        if result is None:
            _render_status_error()
            _render_view()
            return
        content, _name = result
        state["pdf_contour_preview"] = "data:image/png;base64," + base64.b64encode(content).decode("ascii")
        _render_view()

    def _show_dataset_data() -> None:
        state["view_mode"] = "map"
        state["map_target"] = "dataset"
        state["composition_file"] = {}
        state["composition_file_loading"] = False
        state["pdf_contour"] = {}
        state["pdf_contour_loading"] = False
        state["pdf_contour_preview"] = ""
        state["pdf_contour_preview_loading"] = False
        state["pdf_contour_page"] = 0
        state["view_title"] = _dataset_title(_selected_dataset_row()) if state["selected_dataset"] else "Выберите датасет"
        state["view_note"] = "Паспорт, состав и извлечённые данные датасета."
        _render_documents()
        _render_view()

    def _plain_index_text(value: object) -> str:
        text = " ".join(str(value or "").split())
        text = re.sub(r"^#{1,6}\s*", "", text)
        text = re.sub(r"[*_`]+", "", text)
        return text.strip()

    def _indexed_file_brief(file_data: dict) -> str:
        chunks = [item for item in (file_data.get("chunks") or []) if isinstance(item, dict)]
        headings: list[str] = []
        excerpts: list[str] = []
        for item in chunks:
            heading = _plain_index_text(item.get("section_heading") or item.get("parent_heading"))
            if heading and heading not in headings and not heading.lower().startswith("ооо "):
                headings.append(heading)
            text = _plain_index_text(item.get("snippet") or item.get("text"))
            if text:
                excerpts.append(text)
        parts: list[str] = []
        if excerpts:
            excerpt = excerpts[0]
            parts.append(excerpt[:460].rstrip() + ("…" if len(excerpt) > 460 else ""))
        lead = parts[0].casefold() if parts else ""
        sections = [heading for heading in headings if heading.casefold() not in lead][:4]
        if sections:
            parts.append("Разделы: " + "; ".join(sections) + ".")
        return "\n\n".join(parts) or "В проиндексированных фрагментах пока нет текста для краткой справки."

    def _indexed_dataset_brief(brief_data: dict) -> str:
        chunks = [
            chunk
            for document in (brief_data.get("documents") or [])
            if isinstance(document, dict)
            for chunk in (document.get("chunks") or [])
            if isinstance(chunk, dict)
        ]
        headings: list[str] = []
        excerpts: list[str] = []
        for item in chunks:
            heading = _plain_index_text(item.get("section_heading") or item.get("parent_heading"))
            if heading and heading not in headings and not heading.lower().startswith("ооо "):
                headings.append(heading)
            excerpt = _plain_index_text(item.get("snippet") or item.get("text"))
            if excerpt and excerpt not in excerpts:
                excerpts.append(excerpt)
        if not excerpts and not headings:
            return "В Qdrant пока нет текстовых фрагментов, из которых можно собрать справку."
        parts: list[str] = []
        if excerpts:
            lead = excerpts[0]
            parts.append(lead[:430].rstrip() + ("…" if len(lead) > 430 else ""))
        lead_heading = headings[0] if headings else ""
        topics = [heading for heading in headings[1:] if heading.casefold() != lead_heading.casefold()][:4]
        if topics:
            parts.append("В составе индекса: " + "; ".join(topics) + ".")
        documents = [item for item in (state.get("documents") or []) if isinstance(item, dict)]
        folders: set[str] = set()
        for item in documents:
            parts = [part for part in str(item.get("file_name") or "").replace("\\", "/").split("/") if part]
            for depth in range(1, len(parts)):
                folders.add("/".join(parts[:depth]))
        project_pdf = state.get("pdf_extract") if isinstance(state.get("pdf_extract"), dict) else {}
        coverage = project_pdf.get("coverage") if isinstance(project_pdf.get("coverage"), dict) else {}
        pdf_count = int(coverage.get("pdf_documents") or 0)
        if documents:
            composition = f"Состав: {len(documents)} файлов"
            if folders:
                composition += f", {len(folders)} папок"
            if pdf_count:
                composition += f", {pdf_count} PDF"
            parts.append(composition + ".")
        disciplines: list[str] = []
        for item in project_pdf.get("discipline_summaries") or []:
            if not isinstance(item, dict) or not item.get("files"):
                continue
            discipline = str(item.get("discipline") or "").strip()
            if discipline and discipline not in {"UNKNOWN", "PROJECT_TABLES"}:
                disciplines.append(f"{discipline} — {int(item.get('files') or 0)} файлов")
        if disciplines:
            parts.append("Разделы: " + "; ".join(disciplines[:6]) + ".")
        table_summary = coverage.get("project_table_summary") if isinstance(coverage.get("project_table_summary"), dict) else {}
        extracted: list[str] = []
        if int(table_summary.get("detected_tables") or 0):
            extracted.append(f"таблиц — {int(table_summary.get('detected_tables') or 0)}")
        if int(table_summary.get("water_balance_rows") or 0):
            extracted.append(f"строк водного баланса — {int(table_summary.get('water_balance_rows') or 0)}")
        electrical = coverage.get("electrical_summary") if isinstance(coverage.get("electrical_summary"), dict) else {}
        if int(electrical.get("candidate_circuits") or 0):
            extracted.append(f"электрических цепей-кандидатов — {int(electrical.get('candidate_circuits') or 0)}")
        if extracted:
            parts.append("Из документов выделено: " + "; ".join(extracted) + ".")
        return "\n\n".join(parts)

    def _list_warning_messages(warnings: list[str]) -> list[tuple[str, str]]:
        """Turn parser diagnostics into user-facing reading status."""
        values = [str(value or "").strip() for value in warnings if str(value or "").strip()]
        messages: list[tuple[str, str]] = []
        heavy_pages = sum("table_detection_skipped_heavy_vector_page" in value for value in values)
        if heavy_pages:
            messages.append(
                (
                    "info",
                    f"Плотная чертёжная графика на {heavy_pages} стр.: таблицы не выделены автоматически, "
                    "но страницы и текст доступны.",
                )
            )
        if any("missing_pdf_source" in value or "not_pdf_or_missing" in value for value in values):
            messages.append(("action", "Исходный PDF не найден — проверьте путь к файлу."))
        if any("empty_pdf_source" in value for value in values):
            messages.append(("action", "PDF пустой — замените исходный файл."))
        known = (
            "table_detection_skipped_heavy_vector_page",
            "missing_pdf_source",
            "not_pdf_or_missing",
            "empty_pdf_source",
            "project_tables_not_detected",
        )
        other = [value for value in values if not any(marker in value for marker in known)]
        if other:
            messages.append(("action", "Часть структуры не распознана автоматически — откройте документ для проверки."))
        return messages

    def _folder_summary(folder: str, files: list[dict]) -> str:
        prefix = "" if folder == "Корень датасета" else folder.rstrip("/") + "/"
        selected = [item for item in files if not prefix or str(item.get("file_name") or "").startswith(prefix)]
        types: dict[str, int] = {}
        roles: dict[str, int] = {}
        for item in selected:
            kind = _file_kind(str(item.get("file_name") or ""))
            role = str(item.get("doc_role") or item.get("doc_type") or item.get("discipline") or "").strip()
            types[kind] = int(types.get(kind) or 0) + 1
            if role:
                roles[role] = int(roles.get(role) or 0) + 1
        type_text = ", ".join(f"{key} — {value}" for key, value in sorted(types.items(), key=lambda pair: -pair[1])[:4])
        role_text = ", ".join(key for key, _ in sorted(roles.items(), key=lambda pair: -pair[1])[:3])
        parts = [f"{len(selected)} файлов"]
        if type_text:
            parts.append(type_text)
        if role_text:
            parts.append(f"содержание: {role_text}")
        return ". ".join(parts) + "."

    def _short_path(value: str, *, parts: int = 3) -> str:
        chunks = [x for x in str(value or "").split("/") if x]
        if len(chunks) <= parts:
            return str(value or "")
        return ".../" + "/".join(chunks[-parts:])

    def _project_roots(files: list[dict]) -> list[dict]:
        roots: dict[str, dict] = {}
        for item in files:
            file_name = str(item.get("file_name") or "")
            parts = [part for part in file_name.replace("\\", "/").split("/") if part]
            dataset_name = _dataset_title(_selected_dataset_row()).casefold()
            if parts and parts[0].casefold() == dataset_name:
                parts = parts[1:]
            root_name = parts[0] if len(parts) > 1 else "Корень"
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
        state["selected_doc_ids"] = []
        state["chunks"] = []
        state["hits"] = []
        state["dataset_memory"] = {}
        state["memory_loading"] = False
        state["pdf_extract"] = {}
        state["pdf_extract_loading"] = False
        state["pdf_contour"] = {}
        state["pdf_contour_loading"] = False
        state["pdf_contour_preview"] = ""
        state["pdf_contour_preview_loading"] = False
        state["pdf_contour_page"] = 0
        state["operator_guidance"] = ""
        state["selected_folder"] = ""
        state["composition_file"] = {}
        state["composition_file_loading"] = False
        state["map_target"] = "dataset"
        state["document_tree_open"] = []
        state["document_map_files"] = []
        state["document_map_label"] = ""
        state["dataset_index_brief"] = {}
        state["dataset_index_brief_loading"] = False
        state["dataset_integrity"] = {}
        state["dataset_integrity_loading"] = False
        state["dataset_index_quality"] = {}
        state["dataset_index_quality_loading"] = False
        for key in (
            "document_folder_filter", "document_extension_filter",
            "document_status_filter", "document_role_filter",
        ):
            state[key] = ""
        state["dataset_kind"] = str(_selected_dataset_row().get("dataset_kind") or "")
        state["view_mode"] = initial_mode
        state["view_title"] = _dataset_title(_selected_dataset_row()) if dataset_id else "Выберите датасет"
        state["view_note"] = initial_note
        service_upload = refs.get("service_upload")
        if service_upload is not None:
            service_upload.set_visibility(_is_system_dataset())
        await _load_documents()
        await asyncio.gather(
            _load_memory(),
            _load_pdf_extract_summary(),
            _load_dataset_index_brief(),
            _load_rag_readiness(dataset_id),
            _load_dataset_integrity(dataset_id),
            _load_dataset_index_quality(dataset_id),
        )

    async def _load_rag_readiness(dataset_id: str = "", *, force: bool = False) -> None:
        state["rag_readiness_loading"] = True
        params = {}
        if dataset_id:
            params["dataset_id"] = dataset_id
        if force:
            params["force"] = "true"
        suffix = "?" + urlencode(params) if params else ""
        data = await api_get("/api/rag/readiness" + suffix)
        state["rag_readiness_loading"] = False
        state["rag_readiness"] = data if isinstance(data, dict) else {}
        _render_readiness_summary()
        _render_datasets()
        _render_view()

    async def _load_dataset_integrity(dataset_id: str = "") -> None:
        if not dataset_id:
            state["dataset_integrity"] = {}
            return
        state["dataset_integrity_loading"] = True
        _render_view()
        data = await api_get(
            f"/api/rag/datasets/{quote(dataset_id, safe='')}/integrity"
        )
        state["dataset_integrity_loading"] = False
        state["dataset_integrity"] = data if isinstance(data, dict) else {}
        _render_view()

    async def _load_dataset_index_quality(dataset_id: str = "") -> None:
        if not dataset_id:
            state["dataset_index_quality"] = {}
            return
        state["dataset_index_quality_loading"] = True
        _render_view()
        data = await api_get(
            f"/api/documents/datasets/{quote(dataset_id, safe='')}/quality?samples=2"
        )
        state["dataset_index_quality_loading"] = False
        state["dataset_index_quality"] = data if isinstance(data, dict) else {}
        _render_view()

    async def _repair_dataset_integrity() -> None:
        dataset_id = str(state.get("selected_dataset") or "")
        if not dataset_id:
            ui.notify("Сначала выберите датасет", type="warning")
            return
        state["dataset_integrity_loading"] = True
        _render_view()
        data = await api_post(
            f"/api/rag/datasets/{quote(dataset_id, safe='')}/integrity/repair"
        )
        state["dataset_integrity_loading"] = False
        state["dataset_integrity"] = data if isinstance(data, dict) else {}
        if isinstance(data, dict):
            ui.notify(str(data.get("label") or "Проверка завершена"), type="positive")
        else:
            _render_status_error()
        await _load_documents()
        await _load_dataset_index_quality(dataset_id)
        _render_view()

    async def _load_dataset_index_brief() -> None:
        documents = [
            item for item in (state.get("documents") or [])
            if str(item.get("id") or "") and int(item.get("chunk_count") or 0) > 0
        ]
        state["dataset_index_brief_loading"] = True
        state["dataset_index_brief"] = {}
        _render_view()
        ranked = sorted(documents, key=lambda item: -int(item.get("chunk_count") or 0))
        selected: list[dict] = []
        seen_folders: set[str] = set()
        for item in ranked:
            file_name = str(item.get("file_name") or "")
            folder = file_name.rsplit("/", 1)[0] if "/" in file_name else ""
            if folder in seen_folders:
                continue
            seen_folders.add(folder)
            selected.append(item)
            if len(selected) >= 4:
                break
        if len(selected) < 4:
            selected_ids = {str(item.get("id") or "") for item in selected}
            selected.extend(item for item in ranked if str(item.get("id") or "") not in selected_ids)
            selected = selected[:4]
        requests = [
            api_get(
                f"/api/documents/by-id/{quote(str(item.get('id') or ''), safe='')}/chunks?"
                + urlencode({"limit": 8, "max_chars": 1400})
            )
            for item in selected
        ]
        responses = await asyncio.gather(*requests, return_exceptions=True)
        sampled: list[dict] = []
        for document, data in zip(selected, responses):
            if not isinstance(data, dict):
                continue
            sampled.append(
                {
                    "doc_id": str(document.get("id") or ""),
                    "file_name": str(document.get("file_name") or ""),
                    "chunks": list(data.get("chunks") or []),
                    "total": int(data.get("total") or document.get("chunk_count") or 0),
                }
            )
        state["dataset_index_brief_loading"] = False
        state["dataset_index_brief"] = {
            "documents": sampled,
            "sampled_documents": len(sampled),
            "total_fragments": sum(int(item.get("chunk_count") or 0) for item in documents),
            "qdrant": any(
                chunk.get("point_id")
                for item in sampled
                for chunk in (item.get("chunks") or [])
                if isinstance(chunk, dict)
            ),
        }
        _render_view()

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
        state["view_title"] = "CAD/BIM модели"
        state["view_note"] = "Модели, их состав и связь с документами датасета."
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
        params = {"limit": 1000}
        if state["document_filter"].strip():
            params["q"] = state["document_filter"].strip()
        path = f"/api/documents/datasets/{quote(dataset_id, safe='')}/documents?{urlencode(params)}"
        data = await api_get(path)
        if not isinstance(data, dict):
            _render_status_error()
            return
        state["documents"] = sorted(list(data.get("documents") or []), key=_file_sort_key)
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
        _show_dataset_data()

    def _show_cad_inventory() -> None:
        state["view_mode"] = "cad"
        state["view_title"] = "CAD/BIM модели"
        state["view_note"] = "Модели, их состав и связь с документами датасета."
        if not state.get("cad_inventory"):
            _schedule(_load_cad_inventory())
        else:
            _render_view()

    def _office_source_refs() -> list[dict[str, str]]:
        dataset_id = str(state.get("selected_dataset") or "")
        selected = [str(value) for value in (state.get("selected_doc_ids") or []) if str(value)]
        if surface != "studio":
            current = str(state.get("selected_doc_id") or "")
            if current and current not in selected:
                selected.append(current)
            inspected = str((state.get("composition_file") or {}).get("doc_id") or "")
            if inspected and inspected not in selected:
                selected.append(inspected)
        refs_out: list[dict[str, str]] = []
        for doc_id in selected:
            row = _document_by_id(doc_id)
            file_name = str(row.get("file_name") or "")
            if not file_name:
                continue
            refs_out.append({
                "dataset_id": dataset_id,
                "doc_id": doc_id,
                "file_name": file_name,
                "source_ref": file_name,
            })
        return refs_out

    def _office_notify(message: str, *, notification_type: str) -> None:
        """Асинхронные handlers входят в явный UI-slot перед NiceGUI side effect."""
        panel = refs.get("view")
        if panel is None:
            return
        with panel:
            ui.notify(message, type=notification_type)

    async def _load_office_fields(self_render: bool = True) -> None:
        form_id = str(state.get("office_form_id") or "")
        if not form_id:
            state["office_fields"] = []
            if self_render:
                _render_view()
            return
        params = {}
        project_id = str(state.get("office_project_id") or "").strip()
        if project_id:
            params["project_id"] = project_id
        suffix = "?" + urlencode(params) if params else ""
        data = await api_get(f"/api/forms/{quote(form_id, safe='')}/fields{suffix}")
        if isinstance(data, dict):
            fields = list(data.get("fields") or [])
            manual = dict(state.get("office_manual") or {})
            for field in fields:
                if field.get("key") in manual:
                    field["value"] = str(manual.get(field.get("key")) or "")
                    field["needs_input"] = not bool(str(field["value"]).strip())
            state["office_fields"] = fields
        if self_render:
            _render_view()

    async def _load_office_studio(force: bool = False) -> None:
        if state.get("office_loading"):
            return
        state["view_mode"] = "studio"
        state["view_title"] = "Студия документов"
        state["view_note"] = "Черновики DOCX/XLSX с источниками, пропусками и неизменяемыми ревизиями."
        if state.get("office_forms") and not force:
            _render_view()
            return
        state["office_loading"] = True
        _render_view()
        forms_data, projects_data, artifacts_data = await asyncio.gather(
            api_get("/api/forms"),
            api_get("/api/projects"),
            api_get("/api/forms/artifacts?limit=60"),
        )
        state["office_loading"] = False
        state["office_forms"] = list((forms_data or {}).get("forms") or []) if isinstance(forms_data, dict) else []
        state["office_projects"] = list((projects_data or {}).get("projects") or []) if isinstance(projects_data, dict) else []
        state["office_artifacts"] = list((artifacts_data or {}).get("artifacts") or []) if isinstance(artifacts_data, dict) else []
        available_ids = [str(item.get("id") or "") for item in state["office_forms"] if item.get("id")]
        if str(state.get("office_form_id") or "") not in available_ids:
            state["office_form_id"] = available_ids[0] if available_ids else ""
            state["office_manual"] = {}
            state["office_preview"] = ""
        await _load_office_fields(self_render=False)
        _render_view()

    def _show_office_studio() -> None:
        state["view_mode"] = "studio"
        state["view_title"] = "Студия документов"
        state["view_note"] = "Черновики DOCX/XLSX с источниками, пропусками и неизменяемыми ревизиями."
        _render_view()
        _schedule(_load_office_studio())

    async def _select_office_form(form_id: str) -> None:
        state["office_form_id"] = str(form_id or "")
        state["office_manual"] = {}
        state["office_preview"] = ""
        state["office_agent_ir"] = {}
        state["office_agent_applied"] = False
        state["office_review_confirmed"] = False
        await _load_office_fields()

    async def _select_office_project(project_id: str) -> None:
        state["office_project_id"] = str(project_id or "")
        state["office_preview"] = ""
        state["office_agent_ir"] = {}
        state["office_agent_applied"] = False
        state["office_review_confirmed"] = False
        await _load_office_fields()

    def _set_office_manual(key: str, value: object) -> None:
        manual = dict(state.get("office_manual") or {})
        manual[str(key)] = str(value or "")
        state["office_manual"] = manual
        for field in state.get("office_fields") or []:
            if str(field.get("key") or "") == str(key):
                field["value"] = str(value or "")
                field["needs_input"] = not bool(str(value or "").strip())
        state["office_preview"] = ""
        if state.get("office_agent_ir"):
            state["office_review_confirmed"] = False

    def _set_office_review_confirmed(value: object) -> None:
        state["office_review_confirmed"] = bool(value)
        _render_view()

    async def _prepare_office_with_les() -> None:
        form_id = str(state.get("office_form_id") or "")
        if not form_id or state.get("office_agent_running"):
            return
        source_refs = _office_source_refs()
        if not source_refs:
            _office_notify("Выберите хотя бы один файл-основание", notification_type="warning")
            return
        state["office_agent_running"] = True
        state["office_agent_ir"] = {}
        state["office_agent_applied"] = False
        state["office_review_confirmed"] = False
        _render_view()
        project_value = str(state.get("office_project_id") or "").strip()
        payload = {
            "form_id": form_id,
            "project_id": int(project_value) if project_value else None,
            "manual": dict(state.get("office_manual") or {}),
            "dataset_id": str(state.get("selected_dataset") or ""),
            "source_refs": source_refs,
            "instruction": str(state.get("office_instruction") or ""),
        }
        data = await api_post("/api/forms/agent-draft", payload)
        state["office_agent_running"] = False
        if not isinstance(data, dict) or data.get("schema") != "office_document_ir_v1":
            _office_notify(
                last_api_error_text("Л.Е.С. не подготовил поля"),
                notification_type="negative",
            )
            _render_view()
            return
        state["office_agent_ir"] = data
        _office_notify("Предложения Л.Е.С. готовы к проверке", notification_type="positive")
        _render_view()

    def _apply_office_agent_ir() -> None:
        office_ir = state.get("office_agent_ir") if isinstance(state.get("office_agent_ir"), dict) else {}
        proposals = [item for item in (office_ir.get("fields") or []) if isinstance(item, dict)]
        manual = dict(state.get("office_manual") or {})
        applied = 0
        for item in proposals:
            key = str(item.get("key") or "")
            value = str(item.get("value") or "")
            if key and value:
                manual[key] = value
                applied += 1
        state["office_manual"] = manual
        for field in state.get("office_fields") or []:
            key = str(field.get("key") or "")
            if key in manual:
                field["value"] = str(manual.get(key) or "")
                field["needs_input"] = not bool(str(field["value"]).strip())
        state["office_agent_applied"] = True
        state["office_review_confirmed"] = False
        state["office_preview"] = ""
        _office_notify(f"Применено предложений: {applied}", notification_type="positive" if applied else "warning")
        _render_view()

    async def _preview_office_document() -> None:
        form_id = str(state.get("office_form_id") or "")
        if not form_id:
            _office_notify("Выберите шаблон", notification_type="warning")
            return
        project_value = str(state.get("office_project_id") or "").strip()
        payload = {
            "fmt": "html",
            "project_id": int(project_value) if project_value else None,
            "manual": dict(state.get("office_manual") or {}),
        }
        data = await api_post(f"/api/forms/{quote(form_id, safe='')}/generate", payload)
        if not isinstance(data, dict):
            _office_notify(
                last_api_error_text("Не удалось собрать предпросмотр"),
                notification_type="negative",
            )
            return
        resolved = dict(data.get("resolved") or {})
        state["office_fields"] = list(resolved.get("fields") or state.get("office_fields") or [])
        state["office_preview"] = str(data.get("html") or "")
        _render_view()

    async def _create_office_draft() -> None:
        form_id = str(state.get("office_form_id") or "")
        if not form_id or state.get("office_creating"):
            return
        office_ir = state.get("office_agent_ir") if isinstance(state.get("office_agent_ir"), dict) else {}
        if office_ir and not state.get("office_review_confirmed"):
            _office_notify("Подтвердите ручную проверку предложений и источников", notification_type="warning")
            return
        state["office_creating"] = True
        _render_view()
        project_value = str(state.get("office_project_id") or "").strip()
        payload = {
            "form_id": form_id,
            "fmt": str(state.get("office_format") or "docx"),
            "project_id": int(project_value) if project_value else None,
            "manual": dict(state.get("office_manual") or {}),
            "dataset_id": str(state.get("selected_dataset") or ""),
            "source_refs": list(office_ir.get("source_refs") or []) if office_ir else _office_source_refs(),
            "office_ir": office_ir or None,
            "review_confirmed": bool(state.get("office_review_confirmed")),
        }
        data = await api_post("/api/forms/artifacts", payload)
        state["office_creating"] = False
        if not isinstance(data, dict) or not data.get("revision_id"):
            _office_notify(
                last_api_error_text("Не удалось создать черновик"),
                notification_type="negative",
            )
            _render_view()
            return
        state["office_artifacts"] = [data] + [
            item for item in (state.get("office_artifacts") or [])
            if str(item.get("revision_id") or "") != str(data.get("revision_id") or "")
        ]
        missing = len(data.get("missing_fields") or [])
        suffix = f" · незаполненных полей: {missing}" if missing else ""
        _office_notify(
            f"Черновик создан{suffix}",
            notification_type="warning" if missing else "positive",
        )
        _render_view()

    async def _download_office_artifact(revision_id: str) -> None:
        result = await api_get_bytes(
            f"/api/forms/artifacts/{quote(str(revision_id or ''), safe='')}/download"
        )
        if result is None:
            _office_notify(
                last_api_error_text("Не удалось скачать ревизию"),
                notification_type="negative",
            )
            return
        content, filename = result
        panel = refs.get("view")
        if panel is not None:
            with panel:
                ui.download(content, filename)

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

    def _toggle_document_selection(doc_id: str) -> None:
        selected = [str(value) for value in (state.get("selected_doc_ids") or [])]
        if doc_id in selected:
            selected.remove(doc_id)
        else:
            selected.append(doc_id)
        state["selected_doc_ids"] = selected
        _render_documents()
        _render_view()

    def _select_document_group(doc_ids: list[str]) -> None:
        selected = {str(value) for value in (state.get("selected_doc_ids") or []) if str(value)}
        group = {str(value) for value in doc_ids if str(value)}
        if group and group.issubset(selected):
            selected.difference_update(group)
        else:
            selected.update(group)
        state["selected_doc_ids"] = sorted(selected)
        _render_documents()
        _render_view()

    def _activate_document_row(doc_id: str, file_name: str) -> None:
        if surface == "studio":
            _toggle_document_selection(doc_id)
        else:
            _schedule(_inspect_composition_file(doc_id, file_name))

    def _ask_about_selected_documents() -> None:
        selected = {str(value) for value in (state.get("selected_doc_ids") or [])}
        files = [
            str(row.get("file_name") or "")
            for row in (state.get("documents") or [])
            if str(row.get("id") or "") in selected and str(row.get("file_name") or "")
        ]
        dataset_id = str(state.get("selected_dataset") or "")
        if not dataset_id or not files:
            ui.notify("Выберите документы", type="warning")
            return
        params = {
            "scope": f"ds:{dataset_id}",
            "target_files": json.dumps(files, ensure_ascii=False, separators=(",", ":")),
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
        all_files = _composition_files(memory, project_pdf)
        folder_options = sorted(
            {
                "/".join(str(item.get("file_name") or "").split("/")[:-1])
                for item in all_files
                if "/" in str(item.get("file_name") or "")
            }
        )
        extension_options = sorted({_file_kind(str(item.get("file_name") or "")) for item in all_files})
        status_options = sorted({str(item.get("status") or "").upper() for item in all_files if item.get("status")})
        role_options = sorted(
            {
                str(item.get("doc_role") or item.get("doc_type") or item.get("discipline") or "").strip()
                for item in all_files
                if str(item.get("doc_role") or item.get("doc_type") or item.get("discipline") or "").strip()
            }
        )
        folder_filter = str(state.get("composition_folder_filter") or "")
        extension_filter = str(state.get("composition_extension_filter") or "")
        status_filter = str(state.get("composition_status_filter") or "")
        role_filter = str(state.get("composition_role_filter") or "")
        name_filter = str(state.get("composition_name_filter") or "").strip().lower()
        files = []
        for item in all_files:
            file_name = str(item.get("file_name") or "")
            directory = "/".join(file_name.split("/")[:-1])
            role = str(item.get("doc_role") or item.get("doc_type") or item.get("discipline") or "").strip()
            if folder_filter and directory != folder_filter and not directory.startswith(folder_filter.rstrip("/") + "/"):
                continue
            if extension_filter and _file_kind(file_name) != extension_filter:
                continue
            if status_filter and str(item.get("status") or "").upper() != status_filter:
                continue
            if role_filter and role != role_filter:
                continue
            if name_filter and name_filter not in file_name.lower():
                continue
            files.append(item)
        folders: dict[str, dict] = {"": {"name": "Весь датасет", "path": "", "parent": "", "files": []}}
        direct_files: dict[str, list[dict]] = {"": []}
        type_counts: dict[str, int] = {}
        ready = waiting = issues = 0
        for item in files:
            file_name = str(item.get("file_name") or "")
            parts = [part for part in file_name.split("/") if part]
            directory_parts = parts[:-1]
            directory = "/".join(directory_parts)
            direct_files.setdefault(directory, []).append(item)
            for depth in range(1, len(directory_parts) + 1):
                path = "/".join(directory_parts[:depth])
                parent = "/".join(directory_parts[: depth - 1])
                folders.setdefault(path, {"name": directory_parts[depth - 1], "path": path, "parent": parent, "files": []})
            suffix = _file_kind(file_name)
            status = str(item.get("status") or "").upper()
            is_ready = status in {"OK", "INDEXED", "IDLE"}
            is_waiting = status in {"PENDING", "WAITING", "PARSING"}
            ready += int(is_ready)
            waiting += int(is_waiting)
            issues += int(not is_ready and not is_waiting and bool(status))
            type_counts[suffix] = int(type_counts.get(suffix) or 0) + 1
            folders[""]["files"].append(item)
            for depth in range(1, len(directory_parts) + 1):
                folders["/".join(directory_parts[:depth])]["files"].append(item)

        children: dict[str, list[dict]] = {}
        for path, folder in folders.items():
            if not path:
                continue
            children.setdefault(str(folder["parent"]), []).append(folder)
        for rows in children.values():
            rows.sort(key=lambda row: str(row["name"]).lower())

        selected_folder = str(state.get("selected_folder") or "")
        if selected_folder not in folders:
            selected_folder = ""
            state["selected_folder"] = ""
        current = folders[selected_folder]
        current_files = list(current.get("files") or [])
        current_direct_files = list(direct_files.get(selected_folder) or [])
        file_data = state.get("composition_file") or {}

        def _render_pdf_contour_card(doc_id: str) -> None:
            contour = state.get("pdf_contour") if isinstance(state.get("pdf_contour"), dict) else {}
            pages = [page for page in (contour.get("pages") or []) if isinstance(page, dict)]
            with ui.element("section").classes("sov-pdf-contour"):
                with ui.row().classes("items-center w-full sov-pdf-contour-head"):
                    with ui.element("div").classes("sov-pdf-contour-icon"):
                        ui.icon("o_document_scanner")
                    with ui.column().classes("gap-0").style("min-width:0;flex:1;"):
                        _label("Паспорт PDF", size="13px", weight=900)
                        _label(
                            "Постраничная маршрутизация и проверяемое evidence без изменения оригинала.",
                            size="10.5px",
                            color="var(--dim)",
                        )
                    if contour:
                        _badge(
                            "полный" if contour.get("status") == "ready" else "частичный",
                            "tag-ok" if contour.get("status") == "ready" else "tag-warn",
                        )
                if state.get("pdf_contour_loading"):
                    with ui.row().classes("items-center sov-pdf-contour-loading"):
                        ui.spinner(size="sm")
                        _label("Проверяю страницы, текстовый слой, таблицы и штампы…", size="11px", color="var(--dim)")
                    return
                if not contour:
                    _label("Паспорт PDF недоступен: проверьте путь к исходному файлу.", size="10.8px", color="var(--warn)")
                    return
                type_counts = contour.get("page_type_counts") if isinstance(contour.get("page_type_counts"), dict) else {}
                with ui.row().classes("items-center w-full sov-pdf-contour-metrics"):
                    _badge(f"Страниц: {int(contour.get('pages_inspected') or 0)}/{int(contour.get('page_total') or 0)}")
                    ocr_count = int(contour.get("ocr_required_pages") or 0)
                    _badge(f"OCR: {ocr_count}", "tag-warn" if ocr_count else "tag-ok")
                    _badge(f"Таблиц: {int(contour.get('tables_detected') or 0)}")
                    _badge(f"Штампов: {int(contour.get('stamps_detected') or 0)}")
                    if int(type_counts.get("drawing") or 0):
                        _badge(f"Чертежей: {int(type_counts.get('drawing') or 0)}")
                for warning in list(contour.get("warnings") or [])[:2]:
                    _label(str(warning), size="10.5px", color="var(--warn)").classes("sov-pdf-contour-warning")
                selected_page = int(state.get("pdf_contour_page") or (pages[0].get("page") if pages else 0) or 0)
                selected = next((page for page in pages if int(page.get("page") or 0) == selected_page), {})
                if selected:
                    signals = selected.get("signals") if isinstance(selected.get("signals"), dict) else {}
                    geometry = selected.get("geometry") if isinstance(selected.get("geometry"), dict) else {}
                    quality = selected.get("recognition_quality") if isinstance(selected.get("recognition_quality"), dict) else {}
                    stamp = selected.get("stamp") if isinstance(selected.get("stamp"), dict) else {}
                    with ui.element("div").classes("sov-pdf-contour-selected"):
                        with ui.row().classes("items-center w-full sov-pdf-contour-selected-head"):
                            _label(f"Страница {selected_page}", size="12px", weight=900)
                            _badge(str(selected.get("page_type_label") or "Страница"), "tag-warn" if selected.get("requires_ocr") else "tag-ok")
                            _badge(f"уверенность {float(selected.get('routing_confidence') or 0):.0%}")
                            _badge(f"текст {float(quality.get('score') or 0):.0%}")
                        _label(
                            " · ".join(
                                value for value in (
                                    f"{geometry.get('format') or 'лист'} · {geometry.get('orientation') or ''}",
                                    f"{int(signals.get('text_chars') or 0)} знаков",
                                    f"{int(signals.get('drawings') or 0)} графических объектов",
                                    f"{int(signals.get('tables') or 0)} таблиц",
                                    (
                                        f"штамп: {stamp.get('status')}"
                                        if stamp.get("status") and stamp.get("status") != "not_found"
                                        else ""
                                    ),
                                )
                                if value
                            ),
                            size="10.5px",
                            color="var(--dim)",
                        ).classes("sov-pdf-contour-selected-meta")
                        if state.get("pdf_contour_preview_loading"):
                            with ui.element("div").classes("sov-pdf-contour-preview-placeholder"):
                                ui.spinner(size="md")
                        elif state.get("pdf_contour_preview"):
                            ui.image(str(state.get("pdf_contour_preview"))).classes("sov-pdf-contour-preview")
                        fragments = [
                            item for item in (selected.get("evidence_fragments") or []) if isinstance(item, dict)
                        ]
                        if fragments:
                            with ui.expansion(
                                f"Координатные фрагменты · {len(fragments)}",
                                icon="o_my_location",
                                value=False,
                            ).classes("w-full sov-pdf-contour-fragments").props("dense"):
                                for fragment in fragments:
                                    _label(str(fragment.get("source_ref") or ""), size="9.8px", color="var(--dim)")
                                    _label(str(fragment.get("text") or ""), size="10.5px").classes("sov-pdf-contour-fragment-text")
                with ui.element("div").classes("sov-pdf-page-grid"):
                    for page in pages:
                        page_number = int(page.get("page") or 0)
                        is_selected = page_number == selected_page
                        classes = "sov-pdf-page-card sov-pdf-page-card--selected" if is_selected else "sov-pdf-page-card"
                        with ui.element("button").classes(classes).props('type="button"').on(
                            "click", lambda _e, value=page_number: _schedule(_load_pdf_contour_preview(value))
                        ):
                            with ui.row().classes("items-center w-full sov-pdf-page-card-head"):
                                _label(str(page_number), size="13px", weight=900)
                                if page.get("requires_ocr"):
                                    ui.icon("o_document_scanner").props('aria-label="Нужен OCR"')
                            _label(str(page.get("page_type_label") or "Страница"), size="10px", weight=800).classes(
                                "sov-pdf-page-card-type"
                            )
                            geometry = page.get("geometry") if isinstance(page.get("geometry"), dict) else {}
                            _label(str(geometry.get("format") or ""), size="9.5px", color="var(--dim)")

        def _render_file_brief_card() -> None:
            file_name = str(file_data.get("file_name") or "")
            doc_id = str(file_data.get("doc_id") or "")
            document_meta = dict(file_data.get("document") or {})
            inventory_meta = next(
                (item for item in all_files if str(item.get("file_name") or "") == file_name),
                {},
            )
            with ui.element("section").classes("sov-index-brief sov-index-brief--file sov-selected-file-dock"):
                with ui.row().classes("items-center w-full sov-index-brief-kicker"):
                    ui.icon("o_description")
                    _label("Выбранный файл", size="10.5px", color="var(--dim)", weight=850)
                with ui.row().classes("items-center w-full sov-composition-inspector-head"):
                    with ui.element("div").classes("sov-composition-file-icon"):
                        ui.icon(_file_icon(file_name))
                    with ui.column().classes("gap-0").style("min-width:0;flex:1;"):
                        _label(file_name.rsplit("/", 1)[-1], size="15px", weight=900).classes(
                            "sov-composition-file-name"
                        )
                        _label(_short_path(file_name, parts=5), size="10.5px", color="var(--dim)").classes(
                            "sov-composition-file-path"
                        )
                size = inventory_meta.get("file_size") or document_meta.get("file_size")
                role = str(
                    inventory_meta.get("doc_role")
                    or inventory_meta.get("doc_type")
                    or inventory_meta.get("discipline")
                    or document_meta.get("doc_type")
                    or ""
                )
                file_meta = [_file_kind(file_name), _format_size(size) if size else "", role]
                _label("  ·  ".join(value for value in file_meta if value), size="10.5px", color="var(--dim)").classes(
                    "sov-index-brief-meta"
                )
                if state.get("composition_file_loading"):
                    with ui.row().classes("items-center sov-composition-file-loading"):
                        ui.spinner(size="sm")
                        _label("Читаю проиндексированные фрагменты…", size="11px", color="var(--dim)")
                else:
                    chunks = list(file_data.get("chunks") or [])
                    indexed_in_qdrant = any(item.get("point_id") for item in chunks if isinstance(item, dict))
                    _label(_indexed_file_brief(file_data), size="11.4px").classes("sov-index-brief-text")
                    _label(
                        (
                            f"Qdrant/LES: {int(file_data.get('total') or 0)} фрагментов"
                            if indexed_in_qdrant
                            else f"Индекс LES: {int(file_data.get('total') or 0)} фрагментов"
                        ),
                        size="10.3px",
                        color="var(--dim)",
                    ).classes("sov-composition-file-index-source")
                    content_rows: list[tuple[str, str, str]] = []
                    seen_content: set[str] = set()
                    for index, item in enumerate(chunks):
                        if not isinstance(item, dict):
                            continue
                        heading = _plain_index_text(item.get("section_heading") or item.get("parent_heading"))
                        excerpt = _plain_index_text(item.get("snippet") or item.get("text"))
                        if not excerpt:
                            continue
                        key = f"{heading}|{excerpt[:120]}"
                        if key in seen_content:
                            continue
                        seen_content.add(key)
                        page = item.get("page") or item.get("source_page") or item.get("page_number")
                        anchor = f"Стр. {page}" if page else f"Фрагмент {index + 1}"
                        content_rows.append((heading or anchor, excerpt, anchor))
                        if len(content_rows) >= 6:
                            break
                    if content_rows:
                        with ui.element("section").classes("sov-file-content-preview"):
                            _label("Содержание", size="12.5px", weight=900).classes("sov-file-content-title")
                            for heading, excerpt, anchor in content_rows:
                                with ui.element("article").classes("sov-file-content-item"):
                                    with ui.row().classes("items-center w-full sov-file-content-head"):
                                        _label(heading, size="11.4px", weight=850).classes("sov-file-content-heading")
                                        if heading != anchor:
                                            _label(anchor, size="10px", color="var(--dim)").classes("sov-file-content-anchor")
                                    preview = excerpt[:420].rstrip() + ("…" if len(excerpt) > 420 else "")
                                    _label(preview, size="10.8px", color="var(--dim)").classes("sov-file-content-text")
                    if file_name.lower().endswith(".pdf") and doc_id:
                        _render_pdf_contour_card(doc_id)
                    if doc_id and file_name:
                        ui.button(
                            "Открыть оригинал",
                            icon="o_open_in_new",
                            on_click=lambda _e, name=file_name, value=doc_id: _schedule(
                                _open_native_file_name(name, value)
                            ),
                        ).props("unelevated no-caps").classes("sov-composition-open-file")

        def _render_file_row(item: dict, *, compact: bool = False) -> None:
            file_name = str(item.get("file_name") or "")
            doc_id = str(item.get("doc_id") or _document_by_file_name(file_name).get("id") or "")
            inspected = doc_id and doc_id == str((state.get("composition_file") or {}).get("doc_id") or "")
            row_class = "sov-composition-file-row sov-composition-file-row--selected" if inspected else "sov-composition-file-row"
            with ui.element("div").classes(row_class).on(
                "click", lambda _e, value=doc_id, name=file_name: _schedule(_inspect_composition_file(value, name))
            ):
                with ui.element("div").classes("sov-composition-file-icon"):
                    ui.icon(_file_icon(file_name))
                with ui.column().classes("sov-composition-file-copy"):
                    _label(file_name.rsplit("/", 1)[-1], size="11.8px", weight=800).classes("sov-composition-file-name")
                    meta = f"{_file_kind(file_name)} · {_format_size(item.get('file_size'))}"
                    if not compact:
                        meta = f"{_short_path(file_name, parts=4)} · {meta}"
                    _label(meta, size="10.3px", color="var(--dim)").classes("sov-composition-file-path")

        def _render_tree(parent: str = "", depth: int = 0) -> None:
            for folder in children.get(parent, []):
                path = str(folder["path"])
                count = len(folder.get("files") or [])
                with ui.expansion(
                    f"{folder['name']} · {count}",
                    icon="o_folder",
                    value=depth == 0,
                ).classes("w-full sov-composition-tree-node").props("dense"):
                    with ui.element("div").classes("sov-composition-folder-summary-link").on(
                        "click", lambda _e, value=path: _select_composition_folder(value)
                    ):
                        _label(_folder_summary(path, files), size="10.5px", color="var(--dim)")
                    for item in direct_files.get(path, [])[:30]:
                        _render_file_row(item, compact=True)
                    if depth < 5:
                        _render_tree(path, depth + 1)

        if state.get("map_target") == "file" and file_data:
            _render_file_brief_card()
            return

        dataset_brief = state.get("dataset_index_brief") or {}
        with ui.element("section").classes("sov-index-brief sov-index-brief--dataset sov-dataset-brief-fixed"):
            with ui.row().classes("items-center w-full sov-index-brief-kicker"):
                ui.icon("o_auto_stories")
                _label("О датасете", size="10.5px", color="var(--dim)", weight=850)
            _label(_dataset_title(_selected_dataset_row()), size="14px", weight=900).classes("sov-index-brief-title")
            if state.get("dataset_index_brief_loading"):
                with ui.row().classes("items-center sov-composition-file-loading"):
                    ui.spinner(size="sm")
                    _label("Собираю справку из фрагментов Qdrant…", size="11px", color="var(--dim)")
            else:
                _label(_indexed_dataset_brief(dataset_brief), size="11.3px").classes("sov-index-brief-text")
                source_name = "Qdrant/LES" if dataset_brief.get("qdrant") else "Индекс LES"
                fragment_count = f"{int(dataset_brief.get('total_fragments') or 0):,}".replace(",", " ")
                _label(
                    f"{source_name} · {fragment_count} фрагментов · "
                    f"{len(state.get('documents') or [])} файлов в датасете",
                    size="10.3px",
                    color="var(--dim)",
                ).classes("sov-composition-file-index-source")

        with ui.expansion("Реестр датасета", icon="o_inventory_2", value=False).classes("w-full sov-file-registry").props("dense").style(
            "border:1px solid var(--border);border-radius:8px;margin-top:12px;background:var(--bg-panel);"
        ):
            with ui.column().classes("sov-composition-summary"):
                with ui.element("div").classes("sov-composition-overview"):
                    metrics = [
                        (str(len(files)), "файлов" if len(files) == len(all_files) else f"из {len(all_files)} файлов", ""),
                        (str(max(len(folders) - 1, 0)), "папок", ""),
                        (str(ready), "доступно", "good"),
                    ]
                    if waiting:
                        metrics.append((str(waiting), "ожидает", "warn"))
                    if issues:
                        metrics.append((str(issues), "требует внимания", "danger"))
                    for value, caption, tone in metrics:
                        with ui.element("div").classes(f"sov-composition-stat sov-composition-stat--{tone}" if tone else "sov-composition-stat"):
                            _label(value, size="20px", weight=850).classes("sov-composition-stat-value")
                            _label(caption, size="10.5px", color="var(--dim)").classes("sov-composition-stat-caption")
                if type_counts:
                    _label(
                        "  ·  ".join(
                            f"{suffix} {count}" for suffix, count in sorted(type_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:8]
                        ),
                        size="10.7px",
                        color="var(--dim)",
                    ).classes("sov-composition-type-line")
                with ui.row().classes("sov-composition-filters"):
                    folder_select = ui.select(
                        {"": "Все папки", **{value: value for value in folder_options}},
                        value=folder_filter,
                        label="Папка",
                    ).props("outlined dense options-dense")
                    folder_select.on(
                        "update:model-value",
                        lambda e: _set_composition_filter("composition_folder_filter", str(e.args or "")),
                    )
                    extension_select = ui.select(
                        {"": "Все форматы", **{value: value for value in extension_options}},
                        value=extension_filter,
                        label="Расширение",
                    ).props("outlined dense options-dense")
                    extension_select.on(
                        "update:model-value",
                        lambda e: _set_composition_filter("composition_extension_filter", str(e.args or "")),
                    )
                    status_select = ui.select(
                        {"": "Все статусы", **{value: value for value in status_options}},
                        value=status_filter,
                        label="Статус",
                    ).props("outlined dense options-dense")
                    status_select.on(
                        "update:model-value",
                        lambda e: _set_composition_filter("composition_status_filter", str(e.args or "")),
                    )
                    role_select = ui.select(
                        {"": "Все типы", **{value: value for value in role_options}},
                        value=role_filter,
                        label="Тип документа",
                    ).props("outlined dense options-dense")
                    role_select.on(
                        "update:model-value",
                        lambda e: _set_composition_filter("composition_role_filter", str(e.args or "")),
                    )
                    name_input = ui.input(
                        value=name_filter,
                        placeholder="Файл или часть пути…",
                    ).props("outlined dense clearable")
                    name_input.on(
                        "keydown.enter",
                        lambda _e: _set_composition_filter("composition_name_filter", str(name_input.value or "")),
                    )
                with ui.row().classes("sov-composition-view-switch"):
                    for view, icon, label in (
                        ("tree", "o_account_tree", "Дерево"),
                        ("grid", "o_grid_view", "Плитка"),
                        ("list", "o_view_list", "Список"),
                        ("table", "o_table_rows", "Таблица"),
                    ):
                        active = state.get("composition_view") == view
                        ui.button(
                            label,
                            icon=icon,
                            on_click=lambda _e, value=view: _set_composition_view(value),
                        ).props("flat no-caps").classes(
                            "sov-composition-view-btn sov-composition-view-btn--active" if active else "sov-composition-view-btn"
                        )
            if not files:
                _label("Файлы появятся здесь после загрузки списка документов.", size="11.5px", color="var(--dim)").style(
                    "padding:4px 12px 12px;"
                )
                return
            with ui.element("div").classes("sov-composition-browser"):
                with ui.column().classes("sov-composition-navigation"):
                    if state.get("composition_view") == "tree":
                        _render_tree()
                    elif state.get("composition_view") == "table":
                        with ui.element("div").classes("sov-composition-table-wrap"):
                            with ui.element("table").classes("sov-composition-table"):
                                with ui.element("thead"):
                                    with ui.element("tr"):
                                        for heading in ("Файл", "Папка", "Формат", "Статус", "Тип", "Размер"):
                                            with ui.element("th"):
                                                ui.label(heading)
                                with ui.element("tbody"):
                                    for item in current_files[:160]:
                                        file_name = str(item.get("file_name") or "")
                                        doc_id = str(item.get("doc_id") or _document_by_file_name(file_name).get("id") or "")
                                        role = str(item.get("doc_role") or item.get("doc_type") or item.get("discipline") or "—")
                                        with ui.element("tr").on(
                                            "click", lambda _e, value=doc_id, name=file_name: _schedule(
                                                _inspect_composition_file(value, name)
                                            )
                                        ):
                                            for value in (
                                                file_name.rsplit("/", 1)[-1],
                                                _short_path(file_name.rsplit("/", 1)[0] if "/" in file_name else "—", parts=3),
                                                _file_kind(file_name),
                                                str(item.get("status") or "—"),
                                                role,
                                                _format_size(item.get("file_size")),
                                            ):
                                                with ui.element("td"):
                                                    ui.label(value)
                    else:
                        visible_folders = children.get(selected_folder, [])
                        container_cls = "sov-composition-folders" if state.get("composition_view") == "grid" else "sov-composition-folder-list"
                        with ui.column().classes(container_cls):
                            if selected_folder:
                                parent = str(current.get("parent") or "")
                                ui.button(
                                    "На уровень выше",
                                    icon="o_arrow_upward",
                                    on_click=lambda _e, value=parent: _select_composition_folder(value),
                                ).props("flat no-caps").classes("sov-composition-up")
                            for folder in visible_folders:
                                path = str(folder["path"])
                                folder_files = list(folder.get("files") or [])
                                with ui.element("div").classes("sov-composition-folder").on(
                                    "click", lambda _e, value=path: _select_composition_folder(value)
                                ):
                                    with ui.row().classes("items-center w-full sov-composition-folder-head"):
                                        with ui.element("div").classes("sov-composition-folder-icon"):
                                            ui.icon("o_folder")
                                        _label(str(folder["name"]), size="12.5px", weight=850).classes("sov-composition-folder-name")
                                        _label(f"{len(folder_files)} файлов", size="10.5px", color="var(--dim)").classes(
                                            "sov-composition-folder-count"
                                        )
                                    _label(_folder_summary(path, files), size="10.8px", color="var(--dim)").classes("sov-composition-samples")
                            for item in current_direct_files[:40]:
                                _render_file_row(item)

    def _render_dataset_kind_control() -> None:
        with ui.element("div").classes("sov-list-overview").style(
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

    def _readiness_label(value: dict) -> tuple[str, str]:
        state_name = str(value.get("state") or "unknown")
        return {
            "ready": ("RRF готов", "tag-ok"),
            "awaiting_activation": ("Готов к включению", "tag-acc"),
            "building": ("Индексируется", "tag-acc"),
            "degraded": ("Режим деградации", "tag-warn"),
            "blocked": ("Не готов", "tag-warn"),
            "missing": ("Индекс отсутствует", "tag-warn"),
        }.get(state_name, ("Статус неизвестен", "tag-dim"))

    def _render_readiness_summary() -> None:
        panel = refs.get("readiness_summary")
        if panel is None:
            return
        panel.clear()
        with panel:
            if state.get("rag_readiness_loading"):
                ui.spinner(size="sm")
                return
            readiness = state.get("rag_readiness") if isinstance(state.get("rag_readiness"), dict) else {}
            general = readiness.get("general") if isinstance(readiness.get("general"), dict) else {}
            smeta = readiness.get("smeta") if isinstance(readiness.get("smeta"), dict) else {}
            general_label, general_cls = _readiness_label(general)
            mechanical = smeta.get("mechanical_base") if isinstance(smeta.get("mechanical_base"), dict) else {}
            smeta_label = "База готова" if mechanical.get("ready") else "База не готова"
            smeta_cls = "tag-ok" if mechanical.get("ready") else "tag-warn"
            _badge(f"RAG: {general_label}", general_cls)
            _badge(f"Сметы: {smeta_label}", smeta_cls)

    def _render_dataset_integrity_card() -> None:
        result = state.get("dataset_integrity") if isinstance(state.get("dataset_integrity"), dict) else {}
        loading = bool(state.get("dataset_integrity_loading"))
        with ui.element("section").style(
            "border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-top:12px;"
            "background:var(--bg-panel);"
        ):
            with ui.row().classes("items-center w-full").style("gap:8px;flex-wrap:wrap;"):
                ui.icon("o_verified_user").style("font-size:18px;color:var(--accent);")
                _label("Целостность датасета", size="13px", weight=900)
                if loading:
                    ui.spinner(size="sm")
                    _label("Проверяю источники и все каналы поиска…", size="11px", color="var(--dim)")
                ui.element("div").style("flex:1;")
                ui.button(
                    "Проверить и починить",
                    icon="o_build_circle",
                    on_click=lambda: _schedule(_repair_dataset_integrity()),
                ).props("flat dense no-caps").set_enabled(not loading)
            if loading:
                return
            if not result:
                _label("Проверка ещё не выполнялась.", size="11px", color="var(--dim)").style("margin-top:7px;")
                return
            integrity_state = str(result.get("state") or "blocked")
            badge_cls = "tag-ok" if integrity_state == "healthy" else "tag-warn"
            with ui.row().classes("items-center w-full").style("gap:6px;margin-top:9px;flex-wrap:wrap;"):
                _badge(str(result.get("label") or "Статус неизвестен"), badge_cls)
                _badge(f"Проверено файлов: {int(result.get('checked_files') or 0)}")
                _badge(f"Целых: {int(result.get('clean_files') or 0)}", "tag-ok")
                damaged_count = int(result.get("damaged_files") or 0)
                if damaged_count:
                    _badge(f"Повреждено: {damaged_count}", "tag-warn")
                missing_count = int(result.get("missing_files") or 0)
                if missing_count:
                    _badge(f"Нет исходника: {missing_count}", "tag-warn")
            issues = [item for item in (result.get("issues") or []) if isinstance(item, dict)]
            if issues:
                first = issues[0]
                problem = "; ".join(str(value) for value in (first.get("problems") or [])[:3])
                prefix = f"{first.get('file')}: " if first.get("file") else ""
                _label(prefix + problem, size="10.8px", color="var(--warn)").style("margin-top:7px;")

    def _render_dataset_index_quality_card() -> None:
        quality = state.get("dataset_index_quality") if isinstance(state.get("dataset_index_quality"), dict) else {}
        loading = bool(state.get("dataset_index_quality_loading"))
        integrity = state.get("dataset_integrity") if isinstance(state.get("dataset_integrity"), dict) else {}
        checks = {
            str(item.get("file") or ""): item
            for item in (integrity.get("file_checks") or [])
            if isinstance(item, dict) and item.get("file")
        }
        with ui.element("section").classes("sov-index-quality"):
            with ui.row().classes("items-center w-full sov-index-quality-head"):
                ui.icon("o_fact_check")
                _label("Что попало в RAG", size="13px", weight=900)
                if loading:
                    ui.spinner(size="sm")
                    _label("Считаю содержимое поискового индекса…", size="11px", color="var(--dim)")
            if loading:
                return
            if not quality:
                _label("Паспорт содержимого пока недоступен.", size="11px", color="var(--dim)")
                return
            totals = quality.get("totals") if isinstance(quality.get("totals"), dict) else {}
            quality_state = str(quality.get("state") or "empty")
            with ui.row().classes("items-center w-full sov-index-quality-metrics"):
                _badge(str(quality.get("label") or "Статус неизвестен"), "tag-ok" if quality_state == "ready" else "tag-warn")
                _badge(
                    f"Текст есть: {int(totals.get('files_with_searchable_text') or 0)}/{int(totals.get('files') or 0)} файлов"
                )
                _badge(f"Фрагменты: {int(totals.get('indexed_chunks') or 0):,}".replace(",", " "))
                _badge(f"Символы: {int(totals.get('characters') or 0):,}".replace(",", " "))
                if int(totals.get("short_chunks") or 0):
                    _badge(f"Короткие: {int(totals.get('short_chunks') or 0)}", "tag-warn")
                if int(totals.get("empty_chunks") or 0):
                    _badge(f"Пустые: {int(totals.get('empty_chunks') or 0)}", "tag-warn")
            _label(
                " · ".join(str(value) for value in (quality.get("search_channels") or [])),
                size="10.5px",
                color="var(--dim)",
            ).classes("sov-index-quality-channels")
            _label(str(quality.get("operator_note") or ""), size="10.8px", color="var(--dim)").classes(
                "sov-index-quality-note"
            )
            files = [item for item in (quality.get("files") or []) if isinstance(item, dict)]
            with ui.expansion(
                f"По файлам · {len(files)}",
                icon="o_plagiarism",
                value=False,
            ).classes("w-full sov-index-quality-files").props("dense"):
                for item in files[:100]:
                    file_name = str(item.get("file_name") or "")
                    check = checks.get(file_name, {})
                    chunks = int(item.get("indexed_chunks") or 0)
                    declared = int(item.get("declared_chunks") or 0)
                    page_total = int(check.get("expected_text_pages") or 0)
                    page_indexed = int(check.get("indexed_text_pages") or 0)
                    title = f"{file_name.rsplit('/', 1)[-1]} · {chunks}/{declared} фрагм."
                    with ui.expansion(title, icon=_file_icon(file_name)).classes(
                        "w-full sov-index-quality-file"
                    ).props("dense"):
                        metrics = [
                            str(item.get("extension") or "ФАЙЛ"),
                            str(item.get("status") or "статус неизвестен"),
                            f"{int(item.get('characters') or 0):,} симв.".replace(",", " "),
                            f"средний фрагмент {int(item.get('average_chunk_chars') or 0)} симв.",
                        ]
                        if page_total:
                            metrics.append(f"текстовые страницы {page_indexed}/{page_total}")
                        if int(item.get("table_like_chunks") or 0):
                            metrics.append(f"табличных фрагментов {int(item.get('table_like_chunks') or 0)}")
                        _label(" · ".join(metrics), size="10.4px", color="var(--dim)")
                        samples = [sample for sample in (item.get("samples") or []) if isinstance(sample, dict)]
                        if not samples:
                            _label("Текстовых примеров нет.", size="10.7px", color="var(--warn)").style("margin-top:6px;")
                        for sample in samples:
                            heading = str(sample.get("heading") or f"Фрагмент {int(sample.get('chunk_ord') or 0)}")
                            _label(heading, size="10.8px", weight=850).style("margin-top:7px;")
                            _label(str(sample.get("text") or ""), size="10.5px", color="var(--dim)").classes(
                                "sov-index-quality-sample"
                            )
                if len(files) > 100:
                    _label(f"Показаны первые 100 из {len(files)} файлов.", size="10.7px", color="var(--dim)")

    def _render_rag_readiness_card() -> None:
        readiness = state.get("rag_readiness") if isinstance(state.get("rag_readiness"), dict) else {}
        general = readiness.get("general") if isinstance(readiness.get("general"), dict) else {}
        smeta = readiness.get("smeta") if isinstance(readiness.get("smeta"), dict) else {}
        with ui.element("section").style(
            "border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-top:12px;"
            "background:var(--bg-panel);"
        ):
            with ui.row().classes("items-center w-full").style("gap:8px;flex-wrap:wrap;"):
                ui.icon("o_hub").style("font-size:18px;color:var(--accent);")
                _label("Готовность поиска", size="13px", weight=900)
                if state.get("rag_readiness_loading"):
                    ui.spinner(size="sm")
                ui.element("div").style("flex:1;")
                ui.button(
                    "Проверить",
                    icon="o_refresh",
                    on_click=lambda: _schedule(
                        _load_rag_readiness(str(state.get("selected_dataset") or ""), force=True)
                    ),
                ).props("flat dense no-caps")
            if not readiness:
                _label("Статус RAG пока недоступен.", size="11px", color="var(--dim)").style("margin-top:8px;")
                return
            general_label, general_cls = _readiness_label(general)
            mechanical = smeta.get("mechanical_base") if isinstance(smeta.get("mechanical_base"), dict) else {}
            smeta_label = "Механическая база готова" if mechanical.get("ready") else "Механическая база не готова"
            smeta_cls = "tag-ok" if mechanical.get("ready") else "tag-warn"
            with ui.row().classes("items-center w-full").style("gap:6px;margin-top:9px;flex-wrap:wrap;"):
                _badge(general_label, general_cls)
                _badge(f"dense {int(general.get('dense_points') or 0)}/{int(general.get('points') or 0)}")
                _badge(f"sparse {int(general.get('sparse_points') or 0)}/{int(general.get('points') or 0)}")
                _badge("RRF" if general.get("rrf_ready") else "RRF не готов", "tag-ok" if general.get("rrf_ready") else "tag-warn")
                contract = str(general.get("contract_status") or "unknown")
                _badge(f"contract: {contract}", "tag-ok" if general.get("contract_compatible") else "tag-warn")
            expected = general.get("expected_source_points")
            if expected is not None and int(expected or 0) != int(general.get("points") or 0):
                _label(
                    f"Датасет: в реестре {int(expected or 0)} частей, в активном индексе {int(general.get('points') or 0)}.",
                    size="11px",
                    color="var(--warn)",
                ).style("margin-top:7px;")
            with ui.row().classes("items-center w-full").style("gap:6px;margin-top:10px;flex-wrap:wrap;"):
                _badge(f"Сметы: {smeta_label}", smeta_cls)
                _badge(f"{float(smeta.get('progress_pct') or 0):.1f}%")
                _badge(f"dense {int(smeta.get('dense_points') or 0)}/{int(smeta.get('expected_points') or 0)}")
                _badge(f"sparse {int(smeta.get('sparse_points') or 0)}/{int(smeta.get('expected_points') or 0)}")
                search_index = smeta.get("search_index") if isinstance(smeta.get("search_index"), dict) else {}
                _badge(
                    "Поиск по карточкам готов" if search_index.get("ready") else "Карточки норм не построены (необязательно)",
                    "tag-ok" if search_index.get("ready") else "tag-dim",
                )
            quality = smeta.get("quality_probe") if isinstance(smeta.get("quality_probe"), dict) else {}
            if quality.get("status") == "measured":
                _label(
                    "Диагностика каналов: "
                    f"dense и sparse участвовали в top-5 для {int(quality.get('both_channels_in_rrf_top5') or 0)} "
                    f"из {int(quality.get('queries') or 0)} запросов. "
                    "Это проверка retrieval, а не подтверждение применимости норм.",
                    size="10.8px",
                    color="var(--dim)",
                ).style("margin-top:7px;")
            with ui.expansion("Технические детали", icon="o_tune").props("dense").classes("w-full").style("margin-top:7px;"):
                _label(
                    f"Общий alias: {general.get('alias') or '—'} → {general.get('physical_generation') or '—'}",
                    size="10.5px",
                    color="var(--dim)",
                )
                _label(
                    f"Сметный alias: {smeta.get('alias') or '—'} → {smeta.get('physical_generation') or '—'}",
                    size="10.5px",
                    color="var(--dim)",
                )
                _label(
                    f"Embedding: {smeta.get('embedding_model') or '—'} · backend {smeta.get('embedding_backend') or '—'}",
                    size="10.5px",
                    color="var(--dim)",
                )

    def _render_interactive_project_map(
        files: list[dict],
        disciplines: list[dict],
        coverage: dict,
    ) -> None:
        selected = _selected_dataset_row()
        roots = _project_roots(files)
        sections = [
            item
            for item in disciplines
            if int(item.get("files") or 0) > 0
            and str(item.get("discipline") or "") not in {"UNKNOWN", "PROJECT_TABLES"}
        ]
        table_summary = coverage.get("project_table_summary") if isinstance(coverage.get("project_table_summary"), dict) else {}
        electrical = coverage.get("electrical_summary") if isinstance(coverage.get("electrical_summary"), dict) else {}
        metrics = [
            ("Таблицы", int(table_summary.get("detected_tables") or 0), "o_table_view"),
            ("Водный баланс", int(table_summary.get("water_balance_rows") or 0), "o_water_drop"),
            ("Электрические цепи", int(electrical.get("candidate_circuits") or 0), "o_electrical_services"),
            ("Спецификации", int(coverage.get("so_files") or 0), "o_format_list_numbered"),
        ]
        metrics = [item for item in metrics if item[1] > 0]

        with ui.element("section").classes("sov-project-map"):
            with ui.row().classes("items-center w-full sov-project-map-heading"):
                with ui.element("div").classes("sov-project-map-heading-icon"):
                    ui.icon("o_hub")
                with ui.column().classes("gap-0"):
                    _label("Карта проекта", size="13px", weight=900)
                    _label("Папки и разделы можно открыть", size="10.5px", color="var(--dim)")
            with ui.element("div").classes("sov-project-map-root"):
                ui.icon("o_dataset")
                with ui.column().classes("gap-0"):
                    _label(str(selected.get("name") or state.get("selected_dataset") or "Датасет"), size="14px", weight=900)
                    _label(
                        f"{len(state.get('documents') or [])} файлов · {int(coverage.get('pdf_documents') or 0)} PDF",
                        size="10.5px",
                        color="var(--dim)",
                    )
            with ui.element("div").classes("sov-project-map-branches"):
                with ui.element("section").classes("sov-project-map-branch"):
                    with ui.row().classes("items-center sov-project-map-branch-title"):
                        ui.icon("o_folder_open")
                        _label("Папки", size="11px", weight=900)
                    for root in roots[:8]:
                        root_name = str(root.get("name") or "Корень")
                        ui.button(
                            f"{root_name}  ·  {int(root.get('files') or 0)}",
                            icon="o_folder",
                            on_click=lambda _e, path=root_name: _focus_document_folder("" if path == "Корень" else path),
                        ).props("flat no-caps").classes("w-full sov-project-map-node")
                with ui.element("section").classes("sov-project-map-branch"):
                    with ui.row().classes("items-center sov-project-map-branch-title"):
                        ui.icon("o_account_tree")
                        _label("Разделы", size="11px", weight=900)
                    if sections:
                        for item in sections[:8]:
                            code = str(item.get("discipline") or "Раздел")
                            ui.button(
                                f"{code}  ·  {int(item.get('files') or 0)}",
                                icon="o_description",
                                on_click=lambda _e, value=code: _filter_documents_from_map(value),
                            ).props("flat no-caps").classes("w-full sov-project-map-node")
                    else:
                        _label("Разделы ещё не определены", size="10.5px", color="var(--dim)").classes(
                            "sov-project-map-empty"
                        )
                with ui.element("section").classes("sov-project-map-branch"):
                    with ui.row().classes("items-center sov-project-map-branch-title"):
                        ui.icon("o_data_object")
                        _label("Извлечено", size="11px", weight=900)
                    for title, value, icon in metrics[:8]:
                        with ui.element("div").classes("sov-project-map-stat"):
                            ui.icon(icon)
                            _label(title, size="10.8px", weight=800).classes("sov-project-map-stat-title")
                            _label(str(value), size="13px", weight=900).classes("sov-project-map-stat-value")

    def _render_project_source_map(memory: dict, project_pdf: dict, coverage: dict) -> None:
        files = _source_map_files(memory, project_pdf)
        map_files = _composition_files(memory, project_pdf)
        disciplines = [item for item in (project_pdf.get("discipline_summaries") or []) if isinstance(item, dict)]
        roots = _project_roots(map_files)
        if roots:
            _label("Проекты и папки", size="13px", weight=900).style("margin-top:14px;")
            with ui.row().classes("items-stretch w-full").style("gap:8px;flex-wrap:wrap;"):
                for root in roots[:8]:
                    roles = ", ".join(f"{k} {v}" for k, v in list((root.get("roles") or {}).items())[:3])
                    disciplines_text = ", ".join(f"{k} {v}" for k, v in list((root.get("disciplines") or {}).items())[:5])
                    with ui.element("div").classes("sov-list-root-card").style(
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
                    with ui.element("div").classes("sov-list-discipline-card").style(
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
                with ui.element("div").classes("sov-list-file-card").style(
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
                    for tone, message in _list_warning_messages(warnings):
                        _label(
                            message,
                            size="10.5px",
                            color="var(--warn)" if tone == "action" else "var(--dim)",
                        ).style("margin-top:4px;overflow-wrap:anywhere;")
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
            group_filter = str(state.get("dataset_group_filter") or "")
            rows = [
                row for row in state["datasets"]
                if (not kind_filter or str(row.get("dataset_kind") or "") == kind_filter)
                and (not group_filter or _dataset_group(row) == group_filter)
            ]
            if not rows:
                _label("Датасетов с такой меткой нет", color="var(--dim)")
                return
            previous_scope = ""
            for row in rows:
                current_scope = "system" if _is_system_dataset(row) else "user"
                if current_scope != previous_scope:
                    _label(
                        "Служебные" if current_scope == "system" else "Пользовательские",
                        size="10px",
                        color="var(--dim)",
                        weight=900,
                    ).style("margin:8px 2px 2px;text-transform:uppercase;letter-spacing:.05em;")
                    previous_scope = current_scope
                did = str(row.get("id") or "")
                selected = did == state["selected_dataset"]
                selected_cls = " sov-dataset-card--selected" if selected else ""
                with ui.element("div").classes(f"w-full sov-dataset-card{selected_cls}").on(
                    "click", lambda _e, value=did: _schedule(_select_dataset(value))
                ):
                    with ui.row().classes("items-center w-full sov-dataset-card-head"):
                        with ui.element("div").classes("sov-dataset-icon"):
                            ui.icon("o_push_pin" if _is_system_dataset(row) else "o_folder_open")
                        _label(_dataset_title(row), size="13px", weight=850).classes("sov-dataset-name")
                        ui.icon("o_chevron_right").classes("sov-dataset-chevron")
                    status_ready = str(row.get("status", "")).upper() in {"IDLE", "INDEXED"}
                    meta = [
                        "служебный датасет" if _is_system_dataset(row) else (
                            "проект" if _dataset_group(row) == "project" else "база знаний"
                        ),
                        f"{int(row.get('document_count') or 0)} файлов",
                        "готов" if status_ready else "индексируется",
                    ]
                    if selected:
                        readiness = state.get("rag_readiness") if isinstance(state.get("rag_readiness"), dict) else {}
                        general = readiness.get("general") if isinstance(readiness.get("general"), dict) else {}
                        meta.append("RRF готов" if general.get("rrf_ready") else "RRF не готов")
                    _label("  ·  ".join(meta), size="10.5px", color="var(--dim)").classes("sov-dataset-meta-text")
                    pending = int(row.get("pending_count") or 0)
                    errors = int(row.get("error_count") or 0)
                    missing = int(row.get("missing_count") or 0)
                    attention = []
                    if pending:
                        attention.append(f"{pending} ожидает")
                    if errors:
                        attention.append(f"{errors} ошибок")
                    if missing:
                        attention.append(f"{missing} отсутствует")
                    if attention:
                        _label(" · ".join(attention), size="10.3px", color="var(--warn)").classes("sov-dataset-attention")

    async def _upload_service_file(event) -> None:
        dataset_id = str(state.get("selected_dataset") or "")
        if not dataset_id or not _is_system_dataset():
            ui.notify("Сначала выберите служебный датасет", type="warning")
            return
        try:
            upload = getattr(event, "file", None)
            if upload is not None and hasattr(upload, "read"):
                content = await upload.read()
                file_name = getattr(upload, "name", "") or getattr(event, "name", "") or "document.bin"
            else:
                raw = getattr(event, "content", None)
                if raw is None or not hasattr(raw, "read"):
                    raise AttributeError("не удалось прочитать выбранный файл")
                value = raw.read()
                content = await value if inspect.isawaitable(value) else value
                file_name = getattr(event, "name", "") or "document.bin"
            if isinstance(content, str):
                content = content.encode("utf-8")
            if not content:
                raise ValueError("файл пуст")
        except Exception as error:
            ui.notify(f"Не удалось прочитать файл: {error}", type="negative")
            return
        ui.notify(f"Добавляю «{file_name}»", type="info")
        result = await api_post_file(f"/api/rag/upload/{quote(dataset_id, safe='')}", content, file_name)
        if not isinstance(result, dict):
            ui.notify(last_api_error_text("Не удалось добавить файл"), type="negative")
            return
        ui.notify("Файл добавлен. Индексация выполняется в фоне.", type="positive")
        await _load_documents()
        await _load_datasets(select_first=False)

    def _set_dataset_group_filter(group: str) -> None:
        state["dataset_group_filter"] = group
        for value, button in (refs.get("dataset_group_buttons") or {}).items():
            button.classes(remove="sov-dataset-group-btn--active")
            if value == group:
                button.classes(add="sov-dataset-group-btn--active")
        _render_datasets()

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
            selected_ids = {str(value) for value in (state.get("selected_doc_ids") or [])}
            all_documents = [row for row in state["documents"] if isinstance(row, dict)]
            folder_options = sorted(
                {
                    str(row.get("file_name") or "").rsplit("/", 1)[0]
                    for row in all_documents
                    if "/" in str(row.get("file_name") or "")
                },
                key=str.casefold,
            )
            extension_options = sorted({_file_kind(str(row.get("file_name") or "")) for row in all_documents})
            status_options = sorted(
                {str(row.get("status") or "").upper() for row in all_documents if row.get("status")}
            )
            role_options = sorted(
                {
                    str(row.get("doc_type") or row.get("content_type") or row.get("domain") or "").strip()
                    for row in all_documents
                    if str(row.get("doc_type") or row.get("content_type") or row.get("domain") or "").strip()
                },
                key=str.casefold,
            )
            folder_filter = str(state.get("document_folder_filter") or "")
            extension_filter = str(state.get("document_extension_filter") or "")
            status_filter = str(state.get("document_status_filter") or "")
            role_filter = str(state.get("document_role_filter") or "")
            with ui.row().classes("w-full sov-file-panel-filters"):
                folder_select = ui.select(
                    {"": "Все папки", **{value: value for value in folder_options}},
                    value=folder_filter,
                    label="Папка",
                ).props("outlined dense options-dense")
                folder_select.on(
                    "update:model-value",
                    lambda e: _set_document_file_filter("document_folder_filter", str(e.args or "")),
                )
                extension_select = ui.select(
                    {"": "Все форматы", **{value: value for value in extension_options}},
                    value=extension_filter,
                    label="Формат",
                ).props("outlined dense options-dense")
                extension_select.on(
                    "update:model-value",
                    lambda e: _set_document_file_filter("document_extension_filter", str(e.args or "")),
                )
                status_select = ui.select(
                    {"": "Все статусы", **{value: value for value in status_options}},
                    value=status_filter,
                    label="Статус",
                ).props("outlined dense options-dense")
                status_select.on(
                    "update:model-value",
                    lambda e: _set_document_file_filter("document_status_filter", str(e.args or "")),
                )
                status_select.set_visibility(False)
                role_select = ui.select(
                    {"": "Все типы", **{value: value for value in role_options}},
                    value=role_filter,
                    label="Тип",
                ).props("outlined dense options-dense")
                role_select.on(
                    "update:model-value",
                    lambda e: _set_document_file_filter("document_role_filter", str(e.args or "")),
                )
                role_select.set_visibility(False)
            if surface in {"studio", "documents"}:
                with ui.row().classes("items-center w-full").style("gap:6px;padding:2px 4px 6px;"):
                    _label(
                        (
                            f"Файлов-оснований: {len(selected_ids)}"
                            if surface == "studio"
                            else f"Выбрано для вопроса: {len(selected_ids)}"
                        ),
                        size="10.5px",
                        color="var(--dim)",
                        weight=800,
                    ).style("flex:1;")
                    if selected_ids:
                        ui.button(
                            icon="o_close",
                            on_click=lambda: (
                                state.__setitem__("selected_doc_ids", []),
                                _render_documents(),
                                _render_view(),
                            ),
                        ).props('flat round dense aria-label="Снять выбор"')
            dataset_data_button = refs.get("dataset_data_button")
            if dataset_data_button is not None:
                dataset_data_button.classes(remove="sov-dataset-data-button--active")
                if state.get("view_mode") == "map" and state.get("map_target") == "dataset":
                    dataset_data_button.classes(add="sov-dataset-data-button--active")
            needle = str(state.get("document_filter") or "").strip().casefold()
            map_files = {str(value) for value in (state.get("document_map_files") or []) if str(value)}
            rows = [
                row for row in state["documents"]
                if (
                    (map_files and str(row.get("file_name") or "") in map_files)
                    or (not map_files and (not needle or needle in str(row.get("file_name") or "").casefold()))
                )
                and (
                    not folder_filter
                    or str(row.get("file_name") or "").startswith(folder_filter.rstrip("/") + "/")
                )
                and (not extension_filter or _file_kind(str(row.get("file_name") or "")) == extension_filter)
                and (not status_filter or str(row.get("status") or "").upper() == status_filter)
                and (
                    not role_filter
                    or str(row.get("doc_type") or row.get("content_type") or row.get("domain") or "").strip() == role_filter
                )
            ]
            if state.get("document_map_label"):
                with ui.row().classes("items-center w-full sov-document-map-filter"):
                    ui.icon("o_filter_alt")
                    _label(
                        f"Раздел {state.get('document_map_label')} · {len(rows)} файлов",
                        size="10.8px",
                        weight=800,
                    ).style("flex:1;")
                    ui.button(
                        icon="o_close",
                        on_click=lambda: _filter_documents_from_map(""),
                    ).props('flat round dense aria-label="Сбросить фильтр раздела"')
            selected_dataset_name = _dataset_title(_selected_dataset_row()).casefold()
            folders: dict[str, dict] = {"": {"name": "", "path": "", "parent": "", "files": []}}
            direct_files: dict[str, list[dict]] = {"": []}
            for row in rows:
                file_name = str(row.get("file_name") or "")
                parts = [part for part in file_name.split("/") if part]
                if parts and parts[0].casefold() == selected_dataset_name:
                    parts = parts[1:]
                directory_parts = parts[:-1]
                directory = "/".join(directory_parts)
                direct_files.setdefault(directory, []).append(row)
                folders[""]["files"].append(row)
                for depth in range(1, len(directory_parts) + 1):
                    path = "/".join(directory_parts[:depth])
                    parent = "/".join(directory_parts[: depth - 1])
                    folder = folders.setdefault(
                        path,
                        {"name": directory_parts[depth - 1], "path": path, "parent": parent, "files": []},
                    )
                    folder["files"].append(row)
            children: dict[str, list[dict]] = {}
            for path, folder in folders.items():
                if path:
                    children.setdefault(str(folder["parent"]), []).append(folder)
            for items in children.values():
                items.sort(key=lambda item: str(item.get("name") or "").casefold())

            def _render_document_row(row: dict) -> None:
                doc_id = str(row.get("id") or "")
                selected = doc_id in {
                    str(state.get("selected_doc_id") or ""),
                    str((state.get("composition_file") or {}).get("doc_id") or ""),
                } or doc_id in selected_ids
                file_name = str(row.get("file_name") or doc_id)
                basename = file_name.rsplit("/", 1)[-1]
                folder = file_name.rsplit("/", 1)[0] if "/" in file_name else ""
                selected_cls = " sov-document-card--selected" if selected else ""
                with ui.element("div").classes(f"w-full sov-document-card sov-document-card--tree{selected_cls}").on(
                    "click", lambda _e, value=doc_id, name=file_name: _activate_document_row(value, name)
                ):
                    with ui.row().classes("items-center w-full sov-document-card-head"):
                        if surface in {"studio", "documents"}:
                            select_btn = ui.button(
                                icon="o_check_box" if doc_id in selected_ids else "o_check_box_outline_blank",
                            ).props('flat round dense aria-label="Выбрать документ"').classes("sov-icon-btn")
                            select_btn.on("click.stop", lambda _e, value=doc_id: _toggle_document_selection(value))
                        with ui.element("div").classes("sov-document-icon"):
                            ui.icon(_file_icon(file_name))
                        with ui.column().classes("sov-document-copy"):
                            _label(basename, size="12.5px", weight=850).classes("sov-document-name")
                            if folder:
                                _label(_short_path(folder, parts=3), size="10.5px", color="var(--dim)").classes(
                                    "sov-document-path"
                                )
                    indexed = str(row.get("status", "")).upper() == "INDEXED"
                    meta = [
                        _file_kind(file_name),
                        _format_size(row.get("file_size")),
                        "есть в RAG" if indexed else "нет текста в RAG",
                    ]
                    _label("  ·  ".join(meta), size="10.4px", color="var(--dim)").classes("sov-document-meta-text")

            open_paths = {str(item) for item in (state.get("document_tree_open") or []) if str(item)}

            def _render_folder(parent: str = "", depth: int = 0) -> None:
                for folder in children.get(parent, []):
                    path = str(folder.get("path") or "")
                    count = len(folder.get("files") or [])
                    folder_expansion = ui.expansion(
                        f"{folder.get('name') or 'Папка'} · {count}",
                        icon="o_folder",
                        value=bool(needle) or path in open_paths,
                    ).classes("w-full sov-doc-tree-folder").props("dense")
                    folder_expansion.on_value_change(
                        lambda event, value=path: _remember_document_tree_folder(value, bool(event.value))
                    )
                    with folder_expansion:
                        if surface == "studio":
                            group_ids = [
                                str(item.get("id") or "")
                                for item in folder.get("files") or []
                                if str(item.get("id") or "")
                            ]
                            group_selected = bool(group_ids) and set(group_ids).issubset(selected_ids)
                            ui.button(
                                "Снять том" if group_selected else "Выбрать том",
                                icon="o_library_add_check",
                                on_click=lambda _e, values=group_ids: _select_document_group(values),
                            ).props("flat dense no-caps").classes("sov-studio-volume-select")
                        for row in direct_files.get(path, []):
                            _render_document_row(row)
                        if depth < 7:
                            _render_folder(path, depth + 1)

            _render_folder()
            for row in direct_files.get("", []):
                _render_document_row(row)
            if not rows:
                _label("Файлы и папки не найдены", color="var(--dim)")
            if surface == "documents" and selected_ids:
                with ui.element("div").classes("sov-docs-sticky-ask"):
                    with ui.column().classes("gap-0").style("min-width:0;flex:1;"):
                        _label(
                            f"{len(selected_ids)} файл(ов) выбрано",
                            size="12px",
                            weight=900,
                        )
                        _label(
                            "В чате область и список файлов будут закреплены.",
                            size="10.5px",
                            color="var(--dim)",
                        )
                    ui.button(
                        "Спросить в чате",
                        icon="o_forum",
                        on_click=_ask_about_selected_documents,
                    ).props("unelevated no-caps").classes("sov-docs-sticky-ask-button")

    def _render_map() -> None:
        memory = state.get("dataset_memory") or {}
        project_pdf = state.get("pdf_extract") if isinstance(state.get("pdf_extract"), dict) else {}
        if not project_pdf and isinstance(memory, dict):
            project_pdf = memory.get("project_pdf_extract") if isinstance(memory.get("project_pdf_extract"), dict) else {}
        if state.get("map_target") == "file" and state.get("composition_file"):
            _render_file_registry(memory, project_pdf)
            return
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
        _render_dataset_integrity_card()
        _render_dataset_index_quality_card()
        _render_rag_readiness_card()
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

        coverage = project_pdf.get("coverage") if isinstance(project_pdf.get("coverage"), dict) else {}
        disciplines = [item for item in (project_pdf.get("discipline_summaries") or []) if isinstance(item, dict)]
        _render_interactive_project_map(_composition_files(memory, project_pdf), disciplines, coverage)
        _render_file_registry(memory, project_pdf)
        _render_project_source_map(memory, project_pdf, coverage)
        with ui.element("div").classes("sov-docs-coverage"):
            with ui.row().classes("items-center w-full sov-docs-coverage-head"):
                ui.icon("o_picture_as_pdf").style("font-size:18px;color:var(--accent);")
                _label("Покрытие документов", size="13px", weight=900)
                _label("что уже доступно для просмотра", size="11px", color="var(--dim)")
                if state.get("pdf_extract_loading"):
                    ui.spinner(size="sm")
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
                for tone, message in _list_warning_messages(warnings):
                    _label(
                        message,
                        size="11px",
                        color="var(--warn)" if tone == "action" else "var(--dim)",
                    ).style("margin-top:7px;overflow-wrap:anywhere;")
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

    def _render_office_studio() -> None:
        if state.get("office_loading"):
            with ui.row().classes("items-center").style("gap:8px;padding:20px 4px;"):
                ui.spinner(size="sm")
                _label("Загружаю шаблоны и журнал документов…", color="var(--dim)")
            return

        forms = [item for item in (state.get("office_forms") or []) if isinstance(item, dict)]
        if not forms:
            with ui.element("section").style(
                "border:1px dashed var(--border);border-radius:10px;padding:18px;margin-top:12px;"
            ):
                _label("Шаблоны документов не найдены.", size="13px", weight=800)
                ui.button(
                    "Обновить",
                    icon="o_refresh",
                    on_click=lambda: _schedule(_load_office_studio(force=True)),
                ).props("flat dense no-caps").style("margin-top:8px;")
            return

        form_options = {
            str(item.get("id") or ""): str(item.get("title") or item.get("id") or "")
            for item in forms if item.get("id")
        }
        project_options = {"": "Без привязки к объекту"}
        for project in state.get("office_projects") or []:
            if not isinstance(project, dict) or project.get("id") is None:
                continue
            title = str(project.get("name") or project.get("code") or project.get("id"))
            project_options[str(project.get("id"))] = title

        with ui.element("section").style(
            "border:1px solid var(--border);border-radius:10px;padding:14px 16px;"
            "background:var(--bg-panel);"
        ):
            with ui.row().classes("items-center w-full").style("gap:8px;flex-wrap:wrap;"):
                ui.icon("o_edit_document").style("font-size:22px;color:var(--accent);")
                with ui.column().classes("gap-0").style("flex:1;min-width:230px;"):
                    _label("Л.И.С.Т. · Студия документов", size="14px", weight=900)
                    _label(
                        "Оригиналы остаются неизменными. Каждый выпуск — отдельная draft-ревизия с SHA-256.",
                        size="11px",
                        color="var(--dim)",
                    )
                ui.button(
                    "Обновить",
                    icon="o_refresh",
                    on_click=lambda: _schedule(_load_office_studio(force=True)),
                ).props("flat dense no-caps")

            with ui.row().classes("w-full").style("gap:8px;flex-wrap:wrap;margin-top:14px;"):
                form_select = ui.select(
                    form_options,
                    value=str(state.get("office_form_id") or ""),
                    label="Шаблон",
                ).props("outlined dense options-dense").style("min-width:280px;flex:2;")
                form_select.on_value_change(
                    lambda e: _schedule(_select_office_form(str(e.value or ""))),
                )
                project_select = ui.select(
                    project_options,
                    value=str(state.get("office_project_id") or ""),
                    label="Объект",
                ).props("outlined dense options-dense").style("min-width:220px;flex:1;")
                project_select.on_value_change(
                    lambda e: _schedule(_select_office_project(str(e.value or ""))),
                )
                format_select = ui.select(
                    {"docx": "Word · DOCX", "xlsx": "Excel · XLSX"},
                    value=str(state.get("office_format") or "docx"),
                    label="Формат",
                ).props("outlined dense options-dense").style("min-width:150px;")
                format_select.on_value_change(
                    lambda e: state.__setitem__("office_format", str(e.value or "docx")),
                )

        source_refs = _office_source_refs()
        with ui.element("section").style(
            "border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-top:10px;"
        ):
            with ui.row().classes("items-center w-full").style("gap:7px;flex-wrap:wrap;"):
                ui.icon("o_link").style("font-size:18px;color:var(--accent);")
                _label("Основания", size="12.5px", weight=900)
                _badge(str(state.get("selected_dataset") or "датасет не выбран"), "tag-acc" if state.get("selected_dataset") else "tag-dim")
                _badge(f"{len(source_refs)} файлов", "tag-acc" if source_refs else "tag-warn")
            if source_refs:
                for item in source_refs[:8]:
                    _label(f"• {item.get('file_name')}", size="11px", color="var(--dim)").style(
                        "margin-top:4px;overflow-wrap:anywhere;"
                    )
            else:
                _label(
                    "Выберите файлы в средней панели — они будут записаны в manifest как основания черновика.",
                    size="11px",
                    color="var(--dim)",
                ).style("margin-top:6px;")

        with ui.element("section").style(
            "border:1px solid var(--border);border-radius:10px;padding:14px 16px;margin-top:10px;"
            "background:var(--bg-panel);"
        ):
            with ui.row().classes("items-center w-full").style("gap:7px;flex-wrap:wrap;"):
                ui.icon("o_auto_awesome").style("font-size:20px;color:var(--accent);")
                with ui.column().classes("gap-0").style("flex:1;min-width:240px;"):
                    _label("Подготовить с Л.Е.С.", size="13px", weight=900)
                    _label(
                        "Модель читает только выбранные фрагменты и возвращает предложения с evidence. Файл не создаётся.",
                        size="10.8px",
                        color="var(--dim)",
                    )
            instruction_control = ui.textarea(
                value=str(state.get("office_instruction") or ""),
                placeholder="Что подготовить: цель письма, контекст протокола, нужный тон…",
            ).props("outlined dense autogrow").classes("w-full").style("margin-top:10px;")
            instruction_control.on(
                "update:model-value",
                lambda e: state.__setitem__("office_instruction", str(e.args or "")),
            )
            with ui.row().classes("items-center w-full").style("gap:8px;flex-wrap:wrap;margin-top:10px;"):
                prepare_button = ui.button(
                    "Подготовить с Л.Е.С.",
                    icon="o_auto_awesome",
                    on_click=lambda: _schedule(_prepare_office_with_les()),
                ).props("no-caps").classes("sov-docs-search-btn")
                if not source_refs or state.get("office_agent_running"):
                    prepare_button.props("disable")
                if state.get("office_agent_running"):
                    ui.spinner(size="sm")
                    _label("Читаю выбранные документы и собираю IR…", size="11px", color="var(--dim)")

            office_ir = state.get("office_agent_ir") if isinstance(state.get("office_agent_ir"), dict) else {}
            proposals = [item for item in (office_ir.get("fields") or []) if isinstance(item, dict)]
            if office_ir:
                with ui.row().classes("items-center w-full").style("gap:6px;flex-wrap:wrap;margin-top:12px;"):
                    _badge("office_document_ir_v1", "tag-acc")
                    _badge(f"evidence {int(office_ir.get('evidence_count') or 0)}")
                    _badge(f"попыток модели {int(office_ir.get('model_attempts') or 0)}")
                    _badge("файл не создан", "tag-warn")
                for warning in office_ir.get("warnings") or []:
                    _label(f"• {warning}", size="10.8px", color="var(--warn)").style("margin-top:5px;")
                for item in proposals:
                    status = str(item.get("status") or "missing")
                    status_label = {
                        "grounded": "есть основание",
                        "assumption": "предположение",
                        "missing": "не найдено",
                    }.get(status, status)
                    status_cls = "tag-acc" if status == "grounded" else "tag-warn"
                    evidence_rows = [row for row in (item.get("evidence") or []) if isinstance(row, dict)]
                    with ui.element("div").style(
                        "border-top:1px solid var(--border);padding-top:10px;margin-top:10px;"
                    ):
                        with ui.row().classes("items-center w-full").style("gap:6px;flex-wrap:wrap;"):
                            _label(str(item.get("label") or item.get("key") or "Поле"), size="11.5px", weight=850).style(
                                "flex:1;min-width:200px;"
                            )
                            _badge(status_label, status_cls)
                            _badge(f"{round(float(item.get('confidence') or 0) * 100)}%")
                        _label(str(item.get("value") or "—"), size="11.8px", color="var(--text)" if item.get("value") else "var(--warn)").style(
                            "white-space:pre-wrap;margin-top:6px;"
                        )
                        if item.get("note"):
                            _label(str(item.get("note")), size="10.5px", color="var(--dim)").style("margin-top:4px;")
                        if evidence_rows:
                            with ui.expansion(f"Основания · {len(evidence_rows)}", icon="o_fact_check", value=False).classes(
                                "w-full"
                            ).props("dense").style("margin-top:5px;"):
                                for evidence in evidence_rows:
                                    _label(
                                        f"{evidence.get('file_name') or 'Файл'} · chunk {evidence.get('chunk_ord')}"
                                        + (f" · {evidence.get('section')}" if evidence.get("section") else ""),
                                        size="10.5px",
                                        weight=800,
                                    )
                                    _label(str(evidence.get("excerpt") or ""), size="10.5px", color="var(--dim)").style(
                                        "white-space:pre-wrap;margin:3px 0 8px;"
                                    )
                with ui.row().classes("items-center w-full").style("gap:8px;flex-wrap:wrap;margin-top:12px;"):
                    ui.button(
                        "Применить к полям",
                        icon="o_playlist_add_check",
                        on_click=_apply_office_agent_ir,
                    ).props("flat no-caps")
                    if state.get("office_agent_applied"):
                        _badge("предложения применены", "tag-acc")
                if state.get("office_agent_applied"):
                    review_checkbox = ui.checkbox(
                        "Я проверил содержание, предположения и источники",
                        value=bool(state.get("office_review_confirmed")),
                    ).props("dense").style("margin-top:8px;")
                    review_checkbox.on(
                        "update:model-value",
                        lambda e: _set_office_review_confirmed(e.args),
                    )

        fields = [item for item in (state.get("office_fields") or []) if isinstance(item, dict)]
        missing_count = sum(1 for item in fields if not str(item.get("value") or "").strip())
        with ui.element("section").style(
            "border:1px solid var(--border);border-radius:10px;padding:14px 16px;margin-top:10px;"
            "background:var(--bg-panel);"
        ):
            with ui.row().classes("items-center w-full").style("gap:7px;flex-wrap:wrap;"):
                _label("Поля документа", size="13px", weight=900).style("flex:1;")
                _badge(
                    "все заполнено" if not missing_count else f"не заполнено: {missing_count}",
                    "tag-acc" if not missing_count else "tag-warn",
                )
            for field in fields:
                key = str(field.get("key") or "")
                label = str(field.get("label") or key)
                source = str(field.get("source") or "manual")
                value = str((state.get("office_manual") or {}).get(key, field.get("value") or ""))
                with ui.element("div").style(
                    "border-top:1px solid var(--border);padding-top:10px;margin-top:10px;"
                ):
                    with ui.row().classes("items-center w-full").style("gap:6px;flex-wrap:wrap;"):
                        _label(label, size="11.5px", weight=800).style("flex:1;min-width:220px;")
                        _badge(source, "tag-dim" if source == "manual" else "tag-acc")
                    if source == "manual" or not value:
                        control = (
                            ui.textarea(value=value, placeholder="Введите содержание…")
                            if key in {"body", "content", "decision", "decisions", "agenda", "assignments", "notes"}
                            else ui.input(value=value, placeholder="Заполните поле…")
                        )
                        control.props("outlined dense autogrow").classes("w-full").style("margin-top:6px;")
                        control.on(
                            "update:model-value",
                            lambda e, field_key=key: _set_office_manual(field_key, e.args),
                        )
                    else:
                        _label(value or "Не найдено в данных объекта", size="12px", color="var(--text)" if value else "var(--warn)").style(
                            "margin-top:6px;white-space:pre-wrap;"
                        )

            with ui.row().classes("items-center w-full").style("gap:8px;flex-wrap:wrap;margin-top:14px;"):
                ui.button(
                    "Предпросмотр",
                    icon="o_preview",
                    on_click=lambda: _schedule(_preview_office_document()),
                ).props("flat no-caps")
                create_button = ui.button(
                    "Создать черновик",
                    icon="o_note_add",
                    on_click=lambda: _schedule(_create_office_draft()),
                ).props("no-caps").classes("sov-docs-search-btn")
                if office_ir and not state.get("office_review_confirmed"):
                    create_button.props("disable")
                if state.get("office_creating"):
                    ui.spinner(size="sm")
                    _label("Собираю файл и manifest…", size="11px", color="var(--dim)")

        if state.get("office_preview"):
            selected_form = next(
                (item for item in forms if str(item.get("id") or "") == str(state.get("office_form_id") or "")),
                {},
            )
            with ui.element("section").style(
                "border:1px solid var(--border);border-radius:10px;padding:22px 24px;margin-top:10px;"
                "background:#fff;color:#202124;box-shadow:0 6px 24px rgba(0,0,0,.08);"
            ):
                _label(str(selected_form.get("title") or "Предпросмотр"), size="16px", color="#202124", weight=900)
                for field in state.get("office_fields") or []:
                    _label(str(field.get("label") or field.get("key") or ""), size="10px", color="#687078", weight=700).style("margin-top:12px;")
                    _label(str(field.get("value") or "—"), size="12px", color="#202124").style("white-space:pre-wrap;")

        artifacts = [item for item in (state.get("office_artifacts") or []) if isinstance(item, dict)]
        with ui.element("section").style(
            "border:1px solid var(--border);border-radius:10px;padding:14px 16px;margin-top:10px;"
        ):
            with ui.row().classes("items-center w-full").style("gap:7px;"):
                ui.icon("o_history").style("font-size:18px;color:var(--accent);")
                _label("Ревизии Студии", size="13px", weight=900).style("flex:1;")
                _badge(str(len(artifacts)))
            if not artifacts:
                _label("Черновиков пока нет.", size="11px", color="var(--dim)").style("margin-top:8px;")
            for item in artifacts[:30]:
                artifact = dict(item.get("artifact") or {})
                missing = len(item.get("missing_fields") or [])
                with ui.element("div").style("border-top:1px solid var(--border);padding:10px 0;margin-top:8px;"):
                    with ui.row().classes("items-center w-full").style("gap:7px;flex-wrap:wrap;"):
                        _badge(str(item.get("format") or "").upper(), "tag-acc")
                        _badge(f"r{int(item.get('revision_no') or 0)}")
                        if missing:
                            _badge(f"пропуски {missing}", "tag-warn")
                        _label(str(item.get("title") or artifact.get("filename") or "Документ"), size="11.5px", weight=800).style(
                            "flex:1;min-width:220px;"
                        )
                        ui.button(
                            "Скачать",
                            icon="o_download",
                            on_click=lambda _e, revision_id=str(item.get("revision_id") or ""): _schedule(
                                _download_office_artifact(revision_id)
                            ),
                        ).props("flat dense no-caps")
                    _label(
                        f"{item.get('created_at') or ''} · SHA-256 {str(artifact.get('sha256') or '')[:12]}… · "
                        f"оснований {len(item.get('source_refs') or [])}",
                        size="10.5px",
                        color="var(--dim)",
                    ).style("margin-top:4px;")

    def _render_document_reader() -> None:
        """One-purpose document view: indexed content plus the original file."""
        file_data = state.get("composition_file") if isinstance(state.get("composition_file"), dict) else {}
        selected_doc_id = str(file_data.get("doc_id") or state.get("selected_doc_id") or "")
        selected_name = str(file_data.get("file_name") or state.get("selected_doc_name") or "")
        if state.get("composition_file_loading"):
            with ui.row().classes("items-center sov-document-reader-loading"):
                ui.spinner(size="sm")
                _label("Читаю содержимое из RAG…", size="12px", color="var(--dim)")
            return
        if state.get("hits"):
            rows = [item for item in state.get("hits") or [] if isinstance(item, dict)]
            with ui.element("section").classes("sov-document-reader-summary"):
                _label(
                    f"Результаты поиска · {len(rows)}",
                    size="13px",
                    weight=900,
                ).classes("sov-document-reader-heading")
                _label(
                    "Показаны фрагменты, которые реально есть в индексе.",
                    size="11px",
                    color="var(--dim)",
                ).classes("sov-document-reader-note")
        elif selected_doc_id:
            rows = [item for item in file_data.get("chunks") or state.get("chunks") or [] if isinstance(item, dict)]
            with ui.element("section").classes("sov-document-reader-summary"):
                with ui.row().classes("items-center w-full sov-document-reader-file"):
                    with ui.element("div").classes("sov-document-reader-icon"):
                        ui.icon(_file_icon(selected_name))
                    with ui.column().classes("gap-0").style("min-width:0;flex:1;"):
                        _label(
                            selected_name.rsplit("/", 1)[-1] or "Документ",
                            size="15px",
                            weight=900,
                        ).classes("sov-document-reader-heading")
                        _label(
                            f"В RAG: {int(file_data.get('total') or len(rows))} фрагментов",
                            size="11px",
                            color="var(--dim)",
                        ).classes("sov-document-reader-note")
                    ui.button(
                        "Показать оригинал",
                        icon="o_open_in_new",
                        on_click=lambda _e, name=selected_name, value=selected_doc_id: _schedule(
                            _open_native_file_name(name, value)
                        ),
                    ).props("unelevated no-caps").classes(
                        "sov-document-reader-original"
                    )
        elif state.get("selected_dataset"):
            indexed = sum(
                1
                for item in state.get("documents") or []
                if str(item.get("status") or "").upper() == "INDEXED"
            )
            with ui.element("section").classes("sov-document-reader-empty"):
                ui.icon("o_description")
                _label("Выберите файл", size="14px", weight=900)
                _label(
                    f"В этом датасете доступно файлов: {indexed}.",
                    size="11.5px",
                    color="var(--dim)",
                )
            return
        else:
            with ui.element("section").classes("sov-document-reader-empty"):
                ui.icon("o_folder_open")
                _label("Выберите датасет и файл", size="14px", weight=900)
            return

        if not rows:
            with ui.element("section").classes("sov-document-reader-empty"):
                _label("Извлечённого текста для этого файла нет.", size="12px", color="var(--dim)")
            return
        _label("Что есть в RAG", size="13px", weight=900).classes(
            "sov-document-reader-section-title"
        )
        for index, item in enumerate(rows[:40], 1):
            doc_name = str(item.get("doc_name") or selected_name or "")
            heading = _plain_index_text(
                item.get("section_heading") or item.get("parent_heading")
            )
            text = str(item.get("snippet") or item.get("text") or "").strip()
            page = item.get("page") or item.get("source_page") or item.get("page_number")
            with ui.element("article").classes("sov-document-reader-fragment"):
                with ui.row().classes("items-center w-full sov-document-reader-fragment-head"):
                    _label(
                        heading or (f"Страница {page}" if page else f"Фрагмент {index}"),
                        size="12px",
                        weight=850,
                    ).classes("sov-document-reader-fragment-title")
                    if doc_name and (state.get("hits") or doc_name != selected_name):
                        _label(
                            doc_name.rsplit("/", 1)[-1],
                            size="10.5px",
                            color="var(--dim)",
                        ).classes("sov-document-reader-source")
                    result_doc_id = str(item.get("doc_id") or "")
                    if state.get("hits") and result_doc_id:
                        ui.button(
                            icon="o_open_in_new",
                            on_click=lambda _e, value=result_doc_id: _schedule(
                                _open_native_document(value)
                            ),
                        ).props(
                            'flat round aria-label="Показать оригинал"'
                        ).classes("sov-document-reader-result-open").tooltip(
                            "Показать оригинал"
                        )
                _label(text, size="11.5px").classes("sov-document-reader-fragment-text")

    def _render_view() -> None:
        panel = refs.get("view")
        if panel is None:
            return
        panel.clear()
        with panel:
            with ui.row().classes("items-center w-full sov-docs-view-head"):
                with ui.element("div").classes("sov-docs-view-icon"):
                    ui.icon(
                        "o_folder_open"
                        if surface == "documents"
                        else ("o_edit_document" if surface == "studio" else "o_view_in_ar")
                    )
                _label(state["view_title"], size="15px", weight=900).classes("sov-docs-view-title").style(
                    "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;"
                )
            _label(state["view_note"], size="11.5px", color="var(--dim)").classes("sov-docs-view-note")
            if surface == "documents":
                _render_document_reader()
            elif surface == "cad_bim":
                _render_cad_inventory()
            else:
                _render_office_studio()

    def _render_all() -> None:
        _render_datasets()
        _render_documents()
        _render_view()

    async def _load_surface() -> None:
        if surface == "cad_bim":
            await _load_cad_inventory()
            return
        await _load_datasets()
        if surface == "studio":
            await _load_office_studio()

    surface_title = {
        "documents": "Документы",
        "studio": "Студия",
        "cad_bim": "CAD/BIM",
    }[surface]
    surface_subtitle = {
        "documents": "Содержимое в RAG и оригинал файла",
        "studio": "Датасет → том → файлы-основания → проверяемый черновик",
        "cad_bim": "Модели и проекции — отдельно от документов",
    }[surface]

    with ui.column().classes("w-full h-full gap-0 sov-docs-shell sov-ui-shell sov-ui-documents"):
        with ui.row().classes("items-center w-full sov-docs-topbar"):
            with ui.column().classes("sov-docs-heading"):
                _label(surface_title, size="16px", weight=900).classes("sov-docs-title")
                _label(surface_subtitle, size="11.5px", color="var(--dim)").classes(
                    "sov-docs-subtitle"
                )
            q_input = ui.input(placeholder="Найти файл, шифр, раздел или текст…").props("outlined clearable").classes(
                "sov-docs-search sov-ui-input"
            )
            with q_input.add_slot("prepend"):
                ui.icon("o_search")
            q_input.on("update:model-value", lambda e: state.__setitem__("query", str(e.args or "")))
            q_input.on("keydown.enter", lambda _e: _schedule(_search("dataset" if state["selected_dataset"] else "all")))
            with ui.row().classes("items-center").style("gap:5px;flex-wrap:wrap;") as readiness_summary:
                refs["readiness_summary"] = readiness_summary
            search_button = ui.button("Найти", icon="o_search", on_click=lambda: _schedule(_search("dataset" if state["selected_dataset"] else "all"))).props(
                'flat no-caps aria-label="Искать"'
            ).classes("sov-docs-search-btn sov-ui-button")
            if surface == "cad_bim":
                q_input.set_visibility(False)
                readiness_summary.set_visibility(False)
                search_button.set_visibility(False)

        with ui.row().classes("w-full flex-1 no-wrap sov-docs-workspace"):
            with ui.column().classes("h-full no-wrap sov-docs-datasets-panel") as datasets_column:
                with ui.row().classes("items-center w-full sov-docs-panel-title"):
                    ui.icon("o_dataset")
                    _label(
                        "1. Выберите датасет" if surface != "cad_bim" else "Датасеты",
                        size="12px",
                        color="var(--dim)",
                        weight=900,
                    )
                with ui.row().classes("sov-dataset-group-filter"):
                    refs["dataset_group_buttons"] = {}
                    for value, label in DATASET_GROUP_OPTIONS.items():
                        active = str(state.get("dataset_group_filter") or "") == value
                        group_button = ui.button(
                            label,
                            on_click=lambda _e, group=value: _set_dataset_group_filter(group),
                        ).props("flat no-caps").classes(
                            "sov-dataset-group-btn sov-dataset-group-btn--active" if active else "sov-dataset-group-btn"
                        )
                        refs["dataset_group_buttons"][value] = group_button
                dataset_filter = ui.input(placeholder="Название датасета…").props("outlined clearable").classes("sov-docs-filter")
                dataset_filter.on(
                    "update:model-value",
                    lambda e: (state.__setitem__("dataset_filter", str(e.args or "")), _render_datasets()),
                )
                dataset_filter.on("keydown.enter", lambda _e: _schedule(_load_datasets(select_first=True)))
                with ui.column().classes("w-full gap-2 sov-docs-list") as datasets_panel:
                    refs["datasets"] = datasets_panel
                if surface == "cad_bim":
                    datasets_column.set_visibility(False)

            with ui.column().classes("h-full no-wrap sov-docs-files-panel") as files_column:
                with ui.row().classes("items-center w-full sov-docs-panel-title"):
                    ui.icon("o_folder_copy")
                    _label(
                        "2. Тома и файлы-основания" if surface == "studio" else "2. Выберите файлы",
                        size="12px",
                        color="var(--dim)",
                        weight=900,
                    )
                refs["dataset_data_button"] = ui.button(
                    "Данные о датасете",
                    icon="o_dataset",
                    on_click=_show_dataset_data,
                ).props("flat no-caps").classes("w-full sov-dataset-data-button")
                refs["dataset_data_button"].set_visibility(False)
                service_upload = ui.upload(
                    label="Добавить файл",
                    auto_upload=True,
                    max_files=1,
                    on_upload=_upload_service_file,
                ).props("flat accept=.xlsx,.xlsm,.xls,.csv,.pdf,.docx,.md,.txt,.json,.yaml").classes(
                    "w-full sov-dataset-data-button"
                )
                service_upload.set_visibility(False)
                refs["service_upload"] = service_upload
                document_filter = ui.input(placeholder="Название файла…").props("outlined clearable").classes("sov-docs-filter")
                refs["document_filter"] = document_filter
                document_filter.on(
                    "update:model-value",
                    lambda e: _set_document_text_filter(str(e.args or "")),
                )
                document_filter.on("keydown.enter", lambda _e: _schedule(_load_documents()))
                with ui.column().classes("w-full gap-2 sov-docs-list") as documents_panel:
                    refs["documents"] = documents_panel
                if surface == "cad_bim":
                    files_column.set_visibility(False)

            with ui.column().classes("h-full no-wrap sov-docs-view-panel") as view_panel:
                refs["view"] = view_panel
                if surface == "cad_bim":
                    view_panel.style("width:100%;max-width:none;")

    ui.timer(0.15, lambda: _schedule(_load_surface()), once=True)
