"""No-AI document browser for LES datasets.

This page is an operator surface: dataset -> document -> chunks/search. It
does not ask the model anything; it makes the indexed corpus visible.
"""
from __future__ import annotations

import asyncio
import json
import re
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
DATASET_GROUP_OPTIONS = {
    "": "Все",
    "project": "Проекты",
    "other": "Не проекты",
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
        "dataset_group_filter": "",
        "document_filter": "",
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
        "dataset_index_brief": {},
        "dataset_index_brief_loading": False,
        "query": "",
        "view_title": "Выберите датасет",
        "view_note": "Л.И.С.Т. — файловый проводник проекта: структура, данные документов и поиск по индексу.",
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
        return name or "Без названия"

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
        state["view_title"] = _dataset_title(_selected_dataset_row())
        state["view_note"] = "Л.И.С.Т. — файловый проводник проекта: структура, данные документов и поиск по индексу."
        state["composition_file_loading"] = True
        state["composition_file"] = {"doc_id": doc_id, "file_name": file_name}
        _render_documents()
        _render_view()
        data = await api_get(
            f"/api/documents/by-id/{quote(doc_id, safe='')}/chunks?"
            + urlencode({"limit": 12, "max_chars": 1800})
        )
        state["composition_file_loading"] = False
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
        return " ".join(parts)

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
        state["selected_folder"] = ""
        state["composition_file"] = {}
        state["composition_file_loading"] = False
        state["dataset_index_brief"] = {}
        state["dataset_index_brief_loading"] = False
        state["dataset_kind"] = str(_selected_dataset_row().get("dataset_kind") or "")
        state["view_mode"] = "map"
        state["view_title"] = _dataset_title(_selected_dataset_row()) if dataset_id else "Выберите датасет"
        state["view_note"] = "Л.И.С.Т. — файловый проводник проекта: структура, данные документов и поиск по индексу."
        await _load_documents()
        await asyncio.gather(_load_memory(), _load_pdf_extract_summary(), _load_dataset_index_brief())

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
        params = {"limit": 500}
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
        state["view_mode"] = "map"
        state["view_title"] = _dataset_title(_selected_dataset_row()) if state["selected_dataset"] else "Выберите датасет"
        state["view_note"] = "Л.И.С.Т. показывает карту корпуса: описание, проекты, тома, файлы и маршруты чтения."
        _render_view()

    def _show_cad_inventory() -> None:
        state["view_mode"] = "cad"
        state["view_title"] = "CAD/BIM модели"
        state["view_note"] = "Модели, их состав и связь с документами датасета."
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

        with ui.expansion("Состав датасета", icon="o_inventory_2", value=True).classes("w-full sov-file-registry").props("dense").style(
            "border:1px solid var(--border);border-radius:8px;margin-top:12px;background:var(--bg-panel);"
        ):
            with ui.column().classes("sov-composition-summary"):
                dataset_brief = state.get("dataset_index_brief") or {}
                with ui.element("section").classes("sov-index-brief sov-index-brief--dataset"):
                    with ui.row().classes("items-center w-full sov-index-brief-kicker"):
                        ui.icon("o_auto_stories")
                        _label("Справка о датасете", size="10.5px", color="var(--dim)", weight=850)
                    _label(_dataset_title(_selected_dataset_row()), size="15px", weight=900).classes(
                        "sov-index-brief-title"
                    )
                    if state.get("dataset_index_brief_loading"):
                        with ui.row().classes("items-center sov-composition-file-loading"):
                            ui.spinner(size="sm")
                            _label("Собираю справку из фрагментов Qdrant…", size="11px", color="var(--dim)")
                    else:
                        _label(_indexed_dataset_brief(dataset_brief), size="11.5px").classes(
                            "sov-index-brief-text"
                        )
                        source_name = "Qdrant/LES" if dataset_brief.get("qdrant") else "Индекс LES"
                        fragment_count = f"{int(dataset_brief.get('total_fragments') or 0):,}".replace(",", " ")
                        _label(
                            f"{source_name} · {fragment_count} фрагментов · "
                            f"прочитано {int(dataset_brief.get('sampled_documents') or 0)} файла",
                            size="10.3px",
                            color="var(--dim)",
                        ).classes("sov-composition-file-index-source")
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

                with ui.column().classes("sov-composition-inspector"):
                    file_data = state.get("composition_file") or {}
                    if file_data:
                        file_name = str(file_data.get("file_name") or "")
                        doc_id = str(file_data.get("doc_id") or "")
                        document_meta = dict(file_data.get("document") or {})
                        inventory_meta = next(
                            (item for item in all_files if str(item.get("file_name") or "") == file_name),
                            {},
                        )
                        with ui.element("section").classes("sov-index-brief sov-index-brief--file"):
                            with ui.row().classes("items-center w-full sov-index-brief-kicker"):
                                ui.icon("o_description")
                                _label("Справка о файле", size="10.5px", color="var(--dim)", weight=850)
                            with ui.row().classes("items-center w-full sov-composition-inspector-head"):
                                with ui.element("div").classes("sov-composition-file-icon"):
                                    ui.icon(_file_icon(file_name))
                                with ui.column().classes("gap-0").style("min-width:0;flex:1;"):
                                    _label(file_name.rsplit("/", 1)[-1], size="13px", weight=900).classes(
                                        "sov-composition-file-name"
                                    )
                                    _label(_short_path(file_name, parts=4), size="10.5px", color="var(--dim)").classes(
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
                            file_meta = [
                                _file_kind(file_name),
                                _format_size(size) if size else "",
                                role,
                            ]
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
                                if doc_id:
                                    ui.button(
                                        "Открыть текст",
                                        icon="o_article",
                                        on_click=lambda _e, value=doc_id: _schedule(_open_document(value)),
                                    ).props("flat no-caps").classes("sov-composition-open-file")
                    else:
                        with ui.element("section").classes("sov-index-brief sov-index-brief--empty"):
                            with ui.row().classes("items-center w-full sov-index-brief-kicker"):
                                ui.icon("o_description")
                                _label("Справка о файле", size="10.5px", color="var(--dim)", weight=850)
                            _label(
                                "Выберите файл в дереве, списке или таблице — здесь появятся его содержание и источник Qdrant.",
                                size="11.3px",
                                color="var(--dim)",
                            ).classes("sov-index-brief-empty-text")
                    with ui.row().classes("items-center w-full sov-composition-folder-context"):
                        with ui.element("div").classes("sov-composition-folder-icon"):
                            ui.icon("o_folder_open")
                        with ui.column().classes("gap-0").style("min-width:0;flex:1;"):
                            _label(str(current.get("name") or "Весь датасет"), size="12px", weight=850)
                            if selected_folder:
                                _label(selected_folder, size="10.5px", color="var(--dim)").classes("sov-composition-file-path")
                    _label(_folder_summary(selected_folder or "Корень датасета", files), size="11.5px").classes(
                        "sov-composition-folder-description"
                    )

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

    def _render_project_source_map(memory: dict, project_pdf: dict, coverage: dict) -> None:
        files = _source_map_files(memory, project_pdf)
        selected = _selected_dataset_row()
        disciplines = [item for item in (project_pdf.get("discipline_summaries") or []) if isinstance(item, dict)]

        with ui.element("div").classes("sov-list-map").style(
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
                if coverage:
                    read_count = int(coverage.get("files_ok") or coverage.get("files_extracted") or 0)
                    issue_count = int(coverage.get("extract_errors") or 0) + int(coverage.get("missing_source") or 0)
                    _badge(f"PDF {coverage.get('pdf_documents', 0)}")
                    _badge(f"прочитано {read_count}")
                    if issue_count:
                        _badge(f"проверить {issue_count}", "tag-warn")
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
            group_filter = str(state.get("dataset_group_filter") or "")
            rows = [
                row for row in state["datasets"]
                if (not kind_filter or str(row.get("dataset_kind") or "") == kind_filter)
                and (not group_filter or _dataset_group(row) == group_filter)
            ]
            if not rows:
                _label("Датасетов с такой меткой нет", color="var(--dim)")
                return
            for row in rows:
                did = str(row.get("id") or "")
                selected = did == state["selected_dataset"]
                selected_cls = " sov-dataset-card--selected" if selected else ""
                with ui.element("div").classes(f"w-full sov-dataset-card{selected_cls}").on(
                    "click", lambda _e, value=did: _schedule(_select_dataset(value))
                ):
                    with ui.row().classes("items-center w-full sov-dataset-card-head"):
                        with ui.element("div").classes("sov-dataset-icon"):
                            ui.icon("o_folder_open")
                        _label(_dataset_title(row), size="13px", weight=850).classes("sov-dataset-name")
                        ui.icon("o_chevron_right").classes("sov-dataset-chevron")
                    status_ready = str(row.get("status", "")).upper() in {"IDLE", "INDEXED"}
                    meta = [
                        "проект" if _dataset_group(row) == "project" else "база знаний",
                        f"{int(row.get('document_count') or 0)} файлов",
                        "готов" if status_ready else "индексируется",
                    ]
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
            for row in state["documents"]:
                doc_id = str(row.get("id") or "")
                selected = doc_id in {
                    str(state.get("selected_doc_id") or ""),
                    str((state.get("composition_file") or {}).get("doc_id") or ""),
                }
                file_name = str(row.get("file_name") or doc_id)
                basename = file_name.rsplit("/", 1)[-1]
                folder = file_name.rsplit("/", 1)[0] if "/" in file_name else ""
                selected_cls = " sov-document-card--selected" if selected else ""
                with ui.element("div").classes(f"w-full sov-document-card{selected_cls}").on(
                    "click", lambda _e, value=doc_id, name=file_name: _schedule(_inspect_composition_file(value, name))
                ):
                    with ui.row().classes("items-center w-full sov-document-card-head"):
                        with ui.element("div").classes("sov-document-icon"):
                            ui.icon(_file_icon(file_name))
                        with ui.column().classes("sov-document-copy"):
                            _label(basename, size="12.5px", weight=850).classes("sov-document-name")
                            if folder:
                                _label(_short_path(folder, parts=3), size="10.5px", color="var(--dim)").classes(
                                    "sov-document-path"
                                )
                    indexed = str(row.get("status", "")).upper() == "INDEXED"
                    meta = [_file_kind(file_name), _format_size(row.get("file_size")), "в индексе" if indexed else "нужна проверка"]
                    _label("  ·  ".join(meta), size="10.4px", color="var(--dim)").classes("sov-document-meta-text")
                    if str(row.get("status") or "").upper() == "SKIPPED" and _file_kind(file_name) in {"RVT", "DWG", "IFC"}:
                        _label("Для просмотра нужна CAD/BIM-проекция", size="10.3px", color="var(--warn)").classes(
                            "sov-document-attention"
                        )

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
            with ui.row().classes("items-center w-full sov-docs-view-head"):
                with ui.element("div").classes("sov-docs-view-icon"):
                    ui.icon("o_folder_open")
                _label(state["view_title"], size="15px", weight=900).classes("sov-docs-view-title").style(
                    "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;"
                )
                with ui.row().classes("sov-docs-view-tabs"):
                    ui.button("Л.И.С.Т.", icon="o_account_tree", on_click=_show_map).props(
                        "flat no-caps"
                    ).classes("sov-docs-view-tab sov-docs-view-tab--active" if state["view_mode"] == "map" else "sov-docs-view-tab")
                    ui.button("Текст", icon="o_article", on_click=_show_fragments).props(
                        "flat no-caps"
                    ).classes("sov-docs-view-tab sov-docs-view-tab--active" if state["view_mode"] == "fragments" else "sov-docs-view-tab")
                    ui.button("CAD/BIM", icon="o_view_in_ar", on_click=_show_cad_inventory).props(
                        "flat no-caps"
                    ).classes("sov-docs-view-tab sov-docs-view-tab--active" if state["view_mode"] == "cad" else "sov-docs-view-tab")
                with ui.button(icon="o_more_horiz").props(
                    'flat round aria-label="Дополнительные действия"'
                ).classes("sov-docs-more"):
                    with ui.menu().classes("sov-tools-menu"):
                        ui.menu_item("Обновить карту", lambda: _schedule(_refresh_memory()))
                        ui.menu_item("Скопировать источники", _copy_sources)
            _label(state["view_note"], size="11.5px", color="var(--dim)").classes("sov-docs-view-note")
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

    with ui.column().classes("w-full h-full gap-0 sov-docs-shell"):
        with ui.row().classes("items-center w-full sov-docs-topbar"):
            with ui.column().classes("sov-docs-heading"):
                _label("Документы", size="16px", weight=900).classes("sov-docs-title")
                _label("Датасеты, файлы и карта проекта", size="11.5px", color="var(--dim)").classes(
                    "sov-docs-subtitle"
                )
            q_input = ui.input(placeholder="Найти файл, шифр, раздел или текст…").props("outlined clearable").classes(
                "sov-docs-search"
            )
            with q_input.add_slot("prepend"):
                ui.icon("o_search")
            q_input.on("update:model-value", lambda e: state.__setitem__("query", str(e.args or "")))
            q_input.on("keydown.enter", lambda _e: _schedule(_search("dataset" if state["selected_dataset"] else "all")))
            ui.button("Найти", icon="o_search", on_click=lambda: _schedule(_search("dataset" if state["selected_dataset"] else "all"))).props(
                'flat no-caps aria-label="Искать"'
            ).classes("sov-docs-search-btn")

        with ui.row().classes("w-full flex-1 no-wrap sov-docs-workspace"):
            with ui.column().classes("h-full no-wrap sov-docs-datasets-panel"):
                with ui.row().classes("items-center w-full sov-docs-panel-title"):
                    ui.icon("o_dataset")
                    _label("Датасеты", size="12px", color="var(--dim)", weight=900)
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

            with ui.column().classes("h-full no-wrap sov-docs-files-panel"):
                with ui.row().classes("items-center w-full sov-docs-panel-title"):
                    ui.icon("o_folder_copy")
                    _label("Файлы", size="12px", color="var(--dim)", weight=900)
                document_filter = ui.input(placeholder="Название файла…").props("outlined clearable").classes("sov-docs-filter")
                document_filter.on("update:model-value", lambda e: state.__setitem__("document_filter", str(e.args or "")))
                document_filter.on("keydown.enter", lambda _e: _schedule(_load_documents()))
                with ui.column().classes("w-full gap-2 sov-docs-list") as documents_panel:
                    refs["documents"] = documents_panel

            with ui.column().classes("h-full no-wrap sov-docs-view-panel") as view_panel:
                refs["view"] = view_panel

    ui.timer(0.15, lambda: _schedule(_load_datasets()), once=True)
