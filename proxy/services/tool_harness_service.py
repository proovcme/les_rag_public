"""Controlled LES tool harness.

The harness exposes small, typed, read-only tools that return evidence packets
and traces. It is intentionally not an autonomous agent loop: the model may use
these results later, but this layer only executes bounded operations.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from backend.converter import normalize_pdf_text
from proxy.services.document_explorer_service import explorer
from proxy.services.notebook_service import build_dataset_notebook
from proxy.services.tool_trace_policy import make_tool_trace, validate_tool_result


TOOL_RESULT_SCHEMA = "les_tool_result_v1"
TOOL_REGISTRY_SCHEMA = "les_tool_registry_v1"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEXT_EXT = {
    ".txt", ".md", ".json", ".jsonl", ".csv", ".tsv", ".xml", ".yaml", ".yml",
    ".html", ".svg", ".py", ".ini", ".cfg", ".sql", ".log",
}
_EXCEL_EXT = {".xlsx", ".xlsm", ".xls", ".csv", ".tsv"}
_PDF_EXT = {".pdf"}
_MAX_TEXT_BYTES = 1_000_000
_FORBIDDEN_PARTS = {
    ".env",
    ".git",
    ".venv",
    "__pycache__",
    "data",
    "dist",
    "logs",
    "local_private_archive",
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    category: str
    summary: str
    args_schema: dict[str, Any]
    returns: str
    side_effects: str = "none"
    approval_required: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "category": self.category,
            "summary": self.summary,
            "args_schema": self.args_schema,
            "returns": self.returns,
            "side_effects": self.side_effects,
            "approval_required": self.approval_required,
            "tags": list(self.tags),
        }


class ToolHarness:
    """Registry + executor for bounded LES tools."""

    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolSpec, Callable[[dict[str, Any]], dict[str, Any]]]] = {}
        self._register_defaults()

    def registry(self, *, category: str = "") -> dict[str, Any]:
        tools = [spec.to_dict() for spec, _handler in self._tools.values()]
        if category:
            tools = [tool for tool in tools if tool.get("category") == category]
        return {
            "schema": TOOL_REGISTRY_SCHEMA,
            "tool_count": len(tools),
            "tools": sorted(tools, key=lambda item: (str(item["category"]), str(item["name"]))),
            "policy": {
                "model_owns_workflow": True,
                "tools_return_evidence_not_final_domain_answers": True,
                "write_tools_require_approval": True,
            },
        }

    def shortlist(
        self,
        question: str,
        *,
        mode: str = "",
        allowed_tools: list[str] | tuple[str, ...] | set[str] | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        terms = _tokens(" ".join([question, mode]))
        allowed = None if allowed_tools is None else {
            str(name).strip() for name in allowed_tools if str(name).strip()
        }
        scored: list[tuple[int, ToolSpec]] = []
        for spec, _handler in self._tools.values():
            if allowed is not None and spec.name not in allowed:
                continue
            haystack = " ".join([spec.name, spec.title, spec.summary, *spec.tags]).casefold()
            score = sum(1 for term in terms if term in haystack)
            if spec.category in {"dataset", "source"} and any(t in terms for t in ("датасет", "документ", "источник", "pdf", "excel")):
                score += 2
            if spec.category == "filesystem" and any(t in terms for t in ("файл", "папк", "filesystem", "диск", "компьютер", "компьютере")):
                score += 2
            if spec.category == "web" and any(t in terms for t in ("agent", "агент", "интернет", "web", "сайт", "актуальн")):
                score += 3
            if spec.category == "workbook" and any(
                t in terms for t in ("лср", "вор", "смета", "xlsx", "ведомост", "excel")
            ):
                score += 6
            if score:
                scored.append((score, spec))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        selected = [spec.to_dict() | {"score": score} for score, spec in scored[: max(1, limit)]]
        seen = {str(item.get("name") or "") for item in selected}
        for name in ("build_lsr_workbook", "build_vor_workbook"):
            if name not in self._tools:
                continue
            if allowed is not None and name not in allowed:
                continue
            if name in seen:
                continue
            selected.append(self._tools[name][0].to_dict() | {"score": 8})
            seen.add(name)
        if not selected:
            selected = [
                self._tools[name][0].to_dict() | {"score": 0}
                for name in ("dataset_map", "search_sources", "read_source")
                if name in self._tools and (allowed is None or name in allowed)
            ][: max(1, limit)]
        return {"schema": "les_tool_shortlist_v1", "question": question, "mode": mode, "tools": selected}

    def call(self, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(args or {})
        if tool not in self._tools:
            return _result(tool=tool, operation="call", inputs=[args], status="missing",
                           result={}, missing=[f"unknown tool: {tool}"], trace="tool not registered")
        spec, handler = self._tools[tool]
        try:
            payload = handler(args)
        except Exception as exc:  # noqa: BLE001 - tool errors must become traceable payloads
            payload = _result(
                tool=spec.name,
                operation="call",
                inputs=[_redact_args(args)],
                status="error",
                result={},
                warnings=[str(exc)[:240]],
                trace=f"{spec.name} failed: {type(exc).__name__}",
            )
        payload.setdefault("spec", spec.to_dict())
        payload["contract_check"] = validate_tool_result(payload)
        return payload

    def _register(self, spec: ToolSpec, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self._tools[spec.name] = (spec, handler)

    def _register_defaults(self) -> None:
        self._register(
            ToolSpec(
                name="dataset_map",
                title="Dataset map",
                category="dataset",
                summary="Return the typed dataset navigation map: topics, sections, routes and operator guidance.",
                args_schema={"dataset_id": "str", "depth": "deep|shallow"},
                returns="dataset navigation packet, not evidence",
                tags=("dataset", "topic_map", "section_map", "notebook", "navigation"),
            ),
            _tool_dataset_map,
        )
        self._register(
            ToolSpec(
                name="search_sources",
                title="Search indexed sources",
                category="source",
                summary="Search lexical chunks inside the selected dataset/document scope.",
                args_schema={"q": "str", "dataset_ids": "list[str]", "doc_name": "str", "doc_id": "str", "limit": "int"},
                returns="ranked indexed chunks with source ids",
                tags=("retrieval", "source", "search", "fts", "doc_filter"),
            ),
            _tool_search_sources,
        )
        self._register(
            ToolSpec(
                name="read_source",
                title="Read indexed source",
                category="source",
                summary="Read ordered indexed chunks from one document by doc_id or dataset_id+doc_name.",
                args_schema={"doc_id": "str", "dataset_id": "str", "doc_name": "str", "q": "str", "limit": "int"},
                returns="ordered chunks or in-document search hits",
                tags=("read", "document", "chunks", "source"),
            ),
            _tool_read_source,
        )
        self._register(
            ToolSpec(
                name="read_pdf_source",
                title="Read PDF source",
                category="source",
                summary="Read indexed text chunks for a PDF document and mark raw page/table extraction as missing when unavailable.",
                args_schema={"doc_id": "str", "dataset_id": "str", "doc_name": "str", "q": "str", "limit": "int"},
                returns="PDF indexed text chunks with warnings about raw extraction limits",
                tags=("pdf", "read", "document", "source"),
            ),
            _tool_read_pdf_source,
        )
        self._register(
            ToolSpec(
                name="look_at_pdf_page",
                title="Посмотреть страницу PDF",
                category="source",
                summary="Render one selected PDF page or bounded region and let the local vision model inspect the actual drawing pixels.",
                args_schema={"doc_id": "str", "dataset_id": "str", "doc_name": "str", "page": "int (1-based)", "question": "str", "bbox": "[x0,y0,x1,y1] normalized"},
                returns="visual observations tied to the original file and page",
                tags=("vision", "drawing", "чертёж", "схема", "графика", "изображение", "лист", "pdf", "page", "посмотри", "глазами"),
            ),
            _tool_look_at_pdf_page,
        )
        self._register(
            ToolSpec(
                name="read_excel_source",
                title="Read Excel source",
                category="source",
                summary="Read indexed text/table chunks for Excel-like sources and mark sheet/range extraction as missing when unavailable.",
                args_schema={"doc_id": "str", "dataset_id": "str", "doc_name": "str", "q": "str", "limit": "int"},
                returns="Excel indexed chunks with warnings about raw sheet/range limits",
                tags=("excel", "xlsx", "csv", "table", "read", "source"),
            ),
            _tool_read_excel_source,
        )
        self._register(
            ToolSpec(
                name="search_project_tables",
                title="Search project tables",
                category="source",
                summary="Search Л.И.С.Т. table cards by meaning, headers, file and semantic type before reading the original table.",
                args_schema={"dataset_id": "str", "q": "str", "semantic_type": "str", "file": "str", "limit": "int"},
                returns="navigation-only table cards with table_id and source_ref",
                tags=("table", "project", "list", "search", "registry", "headers", "смета", "спецификация"),
            ),
            _tool_search_project_tables,
        )
        self._register(
            ToolSpec(
                name="read_project_table",
                title="Read original project table",
                category="source",
                summary="Open one table from its table_id and return exact bounded rows from the original PDF with source_ref.",
                args_schema={"dataset_id": "str", "table_id": "str", "max_rows": "int"},
                returns="source-evidence table headers and rows",
                tags=("table", "project", "read", "pdf", "rows", "source_ref"),
            ),
            _tool_read_project_table,
        )
        self._register(
            ToolSpec(
                name="assemble_project_volume",
                title="Assemble virtual project volume",
                category="dataset",
                summary="Select a virtual project volume by cipher, section or discipline from documentation metadata; never merges files.",
                args_schema={"dataset_id": "str", "index": "str"},
                returns="metadata selection of project stage, volume, sections, components and gaps",
                tags=("project", "documentation", "volume", "cipher", "stage", "section", "metadata", "том", "шифр"),
            ),
            _tool_assemble_project_volume,
        )
        self._register(
            ToolSpec(
                name="build_lsr_workbook",
                title="Собрать ЛСР в Excel",
                category="workbook",
                summary=(
                    "По прикреплённому PDF/XLSX собрать расценённую ЛСР xlsx кодом "
                    "существующего document workflow. Модель не передаёт цены и строки."
                ),
                args_schema={"attachment_id": "str", "question": "str", "project_id": "int"},
                returns="downloadable LSR xlsx built by code, not by the model",
                side_effects="creates_downloadable_workbook",
                approval_required=False,
                tags=("лср", "смета", "xlsx", "excel", "файл", "расценка", "вложение"),
            ),
            _tool_build_lsr_workbook,
        )
        self._register(
            ToolSpec(
                name="build_vor_workbook",
                title="Собрать ВОР в Excel",
                category="workbook",
                summary=(
                    "По прикреплённой спецификации или ведомости собрать ВОР xlsx "
                    "с количествами из исходника, без цен и без выбора норм."
                ),
                args_schema={"attachment_id": "str", "question": "str"},
                returns="downloadable quantities-only VOR xlsx",
                side_effects="creates_downloadable_workbook",
                approval_required=False,
                tags=("вор", "ведомость", "объем", "xlsx", "excel", "файл", "спецификация", "вложение"),
            ),
            _tool_build_vor_workbook,
        )
        self._register(
            ToolSpec(
                name="web_search",
                title="Public web search",
                category="web",
                summary="Search the public internet and return bounded titles, snippets and source URLs; read-only and never a final answer.",
                args_schema={"q": "str", "limit": "int"},
                returns="public search results with direct source URLs",
                tags=("agent", "web", "internet", "search", "актуальный", "интернет", "сайт"),
            ),
            _tool_web_search,
        )
        self._register(
            ToolSpec(
                name="filesystem_roots",
                title="Filesystem roots",
                category="filesystem",
                summary="List read-only filesystem roots allowed for tool access.",
                args_schema={},
                returns="allowed root keys and paths",
                tags=("filesystem", "roots", "whitelist"),
            ),
            _tool_filesystem_roots,
        )
        self._register(
            ToolSpec(
                name="filesystem_list",
                title="Filesystem list",
                category="filesystem",
                summary="List files under an allowed root without leaving the whitelist.",
                args_schema={"root": "str", "path": "str", "depth": "int"},
                returns="bounded directory tree",
                tags=("filesystem", "list", "tree"),
            ),
            _tool_filesystem_list,
        )
        self._register(
            ToolSpec(
                name="filesystem_stat",
                title="Filesystem stat",
                category="filesystem",
                summary="Return metadata for a file or directory under an allowed root.",
                args_schema={"root": "str", "path": "str"},
                returns="file metadata without content",
                tags=("filesystem", "stat", "metadata"),
            ),
            _tool_filesystem_stat,
        )
        self._register(
            ToolSpec(
                name="filesystem_read_text",
                title="Filesystem read text",
                category="filesystem",
                summary="Read a small text file under an allowed root.",
                args_schema={"root": "str", "path": "str", "max_chars": "int"},
                returns="text content with truncation flag",
                tags=("filesystem", "read", "text"),
            ),
            _tool_filesystem_read_text,
        )
        self._register(
            ToolSpec(
                name="filesystem_search",
                title="Filesystem search",
                category="filesystem",
                summary="Search names and optionally text content under an allowed root.",
                args_schema={"root": "str", "path": "str", "q": "str", "content": "bool", "limit": "int"},
                returns="bounded file hits",
                tags=("filesystem", "search", "find"),
            ),
            _tool_filesystem_search,
        )
        self._register(
            ToolSpec(
                name="filesystem_hash",
                title="Filesystem hash",
                category="filesystem",
                summary="Calculate SHA-256 for a file under an allowed root.",
                args_schema={"root": "str", "path": "str"},
                returns="sha256 digest and file size",
                tags=("filesystem", "hash", "sha256"),
            ),
            _tool_filesystem_hash,
        )


def _tool_build_lsr_workbook(args: dict[str, Any]) -> dict[str, Any]:
    from proxy.services.smeta_workbook_tools import build_lsr_workbook

    return build_lsr_workbook(args)


def _tool_build_vor_workbook(args: dict[str, Any]) -> dict[str, Any]:
    from proxy.services.smeta_workbook_tools import build_vor_workbook

    return build_vor_workbook(args)


def _tool_dataset_map(args: dict[str, Any]) -> dict[str, Any]:
    dataset_id = str(args.get("dataset_id") or "").strip()
    if not dataset_id:
        return _result(tool="dataset_map", operation="build", inputs=[args], status="missing",
                       result={}, missing=["dataset_id"], trace="dataset_id is required")
    notebook = build_dataset_notebook(
        dataset_id,
        storage_root=Path(str(args.get("storage_root") or "storage/datasets")),
        depth=str(args.get("depth") or "deep"),
    )
    typed = notebook.get("typed_memory") if isinstance(notebook.get("typed_memory"), dict) else {}
    result = {
        "dataset_id": dataset_id,
        "schema": notebook.get("schema") or "notebook_v1",
        "summary": notebook.get("notebook_summary") or {},
        "operator_guidance": typed.get("operator_guidance") or notebook.get("operator_guidance") or "",
        "topic_map": typed.get("topic_map") or {},
        "section_map": typed.get("section_map") or {},
        "source_layers": typed.get("source_layers") or [],
        "retrieval_routes": typed.get("retrieval_routes") or [],
        "known_gaps": typed.get("known_gaps") or [],
    }
    return _result(
        tool="dataset_map",
        operation="build",
        inputs=[{"dataset_id": dataset_id, "depth": str(args.get("depth") or "deep")}],
        status="ok",
        result=result,
        evidence=[{"kind": "navigation", "dataset_id": dataset_id, "is_evidence": False}],
        trace="built dataset navigation map from notebook/typed memory",
    )


def _tool_search_sources(args: dict[str, Any]) -> dict[str, Any]:
    q = str(args.get("q") or "").strip()
    if not q:
        return _result(tool="search_sources", operation="search", inputs=[args], status="missing",
                       result={}, missing=["q"], trace="query is required")
    dataset_ids = _list_arg(args.get("dataset_ids") or args.get("dataset_id"))
    result = explorer().search(
        q,
        dataset_ids=dataset_ids,
        doc_name=str(args.get("doc_name") or ""),
        doc_id=str(args.get("doc_id") or ""),
        limit=_int_arg(args.get("limit"), 50, min_value=1, max_value=200),
        max_chars=_int_arg(args.get("max_chars"), 1200, min_value=200, max_value=8000),
    )
    return _result(
        tool="search_sources",
        operation="search",
        inputs=[{"q": q, "dataset_ids": dataset_ids, "doc_name": args.get("doc_name") or "", "doc_id": args.get("doc_id") or ""}],
        status="ok" if result.get("count") else "missing",
        result=result,
        sources=_sources_from_rows(result.get("hits") or []),
        missing=[] if result.get("count") else ["no indexed chunks matched query"],
        warnings=[str(result.get("warning"))] if result.get("warning") else [],
        trace="searched lexical chunks through DocumentExplorer",
    )


def _tool_read_source(args: dict[str, Any]) -> dict[str, Any]:
    return _read_source_payload("read_source", args)


def _tool_read_pdf_source(args: dict[str, Any]) -> dict[str, Any]:
    payload = _read_source_payload("read_pdf_source", args)
    doc_name = _result_doc_name(payload)
    warnings = list(payload.get("warnings") or [])
    if doc_name and Path(doc_name).suffix.casefold() not in _PDF_EXT:
        warnings.append("source extension is not pdf")
    warnings.append("raw PDF page/table extraction is not part of this first tool pass; using indexed chunks")
    payload["warnings"] = list(dict.fromkeys(warnings))
    payload["trace"] = str(payload.get("trace") or "") + "; pdf indexed-chunk read"
    if isinstance(payload.get("tool_trace"), dict):
        payload["tool_trace"]["warnings"] = payload["warnings"]
        payload["tool_trace"]["trace"] = payload["trace"]
    payload["contract_check"] = validate_tool_result(payload)
    return payload


def _tool_look_at_pdf_page(args: dict[str, Any]) -> dict[str, Any]:
    """Bounded pixel-level reading; the vision model observes, LES only renders."""
    doc_id = str(args.get("doc_id") or "").strip()
    if doc_id:
        document = explorer().get_document(doc_id)
    else:
        dataset_id = str(args.get("dataset_id") or "").strip()
        doc_name = str(args.get("doc_name") or "").strip()
        document = None
        if dataset_id and doc_name:
            # document_chunks() intentionally returns chunks only. Resolve the real
            # registry row (and therefore source_path) by exact/suffix file name so
            # model calls with a human-visible basename can render the original PDF.
            listed = explorer().list_documents(dataset_id, q=Path(doc_name).name, limit=50)
            candidates = listed.get("documents") or [] if isinstance(listed, dict) else []
            wanted = doc_name.replace("\\", "/").casefold()
            wanted_base = Path(doc_name).name.casefold()
            document = next(
                (
                    item for item in candidates
                    if str(item.get("file_name") or "").replace("\\", "/").casefold() == wanted
                ),
                None,
            ) or next(
                (
                    item for item in candidates
                    if Path(str(item.get("file_name") or "")).name.casefold() == wanted_base
                ),
                None,
            )
    if not isinstance(document, dict):
        return _result(tool="look_at_pdf_page", operation="vision_read", inputs=[args], status="missing",
                       result={}, missing=["PDF document not found"], trace="document selector did not resolve")
    source_path = Path(str(document.get("source_path") or "")).expanduser()
    if source_path.suffix.casefold() != ".pdf" or not source_path.is_file():
        return _result(tool="look_at_pdf_page", operation="vision_read", inputs=[args], status="missing",
                       result={}, missing=["original PDF source is unavailable"], trace="source_path is not a readable PDF")
    page_number = _int_arg(args.get("page"), 1, min_value=1, max_value=100000)
    question = str(args.get("question") or args.get("q") or "Что видно на этом чертеже?").strip()[:2000]
    try:
        import fitz

        with fitz.open(source_path) as pdf:
            if page_number > len(pdf):
                return _result(tool="look_at_pdf_page", operation="vision_read", inputs=[args], status="missing",
                               result={"pages": len(pdf)}, missing=["page is outside the PDF"], trace="page bounds check failed")
            page = pdf[page_number - 1]
            page_text = normalize_pdf_text(page.get_text("text") or "")
            clip = page.rect
            bbox = args.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                values = [max(0.0, min(1.0, float(value))) for value in bbox]
                if values[2] > values[0] and values[3] > values[1]:
                    clip = fitz.Rect(
                        page.rect.x0 + page.rect.width * values[0],
                        page.rect.y0 + page.rect.height * values[1],
                        page.rect.x0 + page.rect.width * values[2],
                        page.rect.y0 + page.rect.height * values[3],
                    )
            def _render(region, target_edge: float) -> str:
                max_edge = max(region.width, region.height, 1.0)
                scale = max(0.5, min(4.0, target_edge / max_edge))
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=region, alpha=False)
                return base64.b64encode(pix.tobytes("png")).decode("ascii")

            # Общий план даёт геометрию, но на больших листах штамп и легенда в нём
            # нечитаемы. Кропы обрабатываются отдельными короткими вызовами: Gemma
            # зависает на трёх больших изображениях в одном запросе.
            image_tasks = [("Весь лист", _render(clip, 2100.0), page_text[:12000])]
            if not (isinstance(bbox, list) and len(bbox) == 4):
                rect = page.rect
                title_clip = fitz.Rect(
                    rect.x0 + rect.width * 0.72,
                    rect.y0 + rect.height * 0.76,
                    rect.x1,
                    rect.y1,
                )
                legend_clip = fitz.Rect(
                    rect.x0 + rect.width * 0.48,
                    rect.y0 + rect.height * 0.72,
                    rect.x0 + rect.width * 0.78,
                    rect.y1,
                )
                image_tasks.extend([
                    (
                        "Штамп",
                        _render(title_clip, 1600.0),
                        normalize_pdf_text(page.get_text("text", clip=title_clip) or "")[:3000],
                    ),
                    (
                        "Легенда",
                        _render(legend_clip, 1600.0),
                        normalize_pdf_text(page.get_text("text", clip=legend_clip) or "")[:4000],
                    ),
                ])
    except Exception as exc:  # noqa: BLE001
        return _result(tool="look_at_pdf_page", operation="vision_read", inputs=[args], status="error",
                       result={}, warnings=[str(exc)[:240]], trace=f"PDF render failed: {type(exc).__name__}")

    model = (
        os.getenv("LES_DRAWING_VISION_MODEL", "").strip()
        or os.getenv("RAG_OCR_MODEL", "").strip()
        or "gemma4:12b"
    )
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    prompt_base = (
        f"Ты рассматриваешь реальную PDF-страницу номер {page_number} (счёт страниц файла, начиная с 1). "
        "Не ищи напечатанный номер страницы и не утверждай, что PDF-страница отсутствует: изображение перед тобой и есть запрошенная страница. "
        "Ответь только о том, что визуально видно: "
        "надписи, марки, размеры, условные обозначения и связи. Не достраивай невидимое. "
        f"Вопрос: {question}"
    )
    try:
        import httpx

        observations: list[str] = []
        for label, image_b64, exact_text in image_tasks:
            focus = {
                "Весь лист": "Определи вид и назначение чертежа по геометрии и маркировкам; мелкий штамп не угадывай.",
                "Штамп": "Прочитай название листа, стадию, номер листа и шифр из штампа. Нечитаемое так и назови.",
                "Легенда": "Прочитай условные обозначения и пояснения легенды. Нечитаемое не угадывай.",
            }.get(label, "Опиши видимое.")
            body = {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": (
                        f"{prompt_base} Область: {label}. {focus}\n"
                        "Ниже точный текстовый слой этой же области; порядок строк может быть нарушен. "
                        "Используй его только для чтения надписей, а геометрию определяй по изображению:\n"
                        f"---\n{exact_text or '[текстового слоя нет]'}\n---"
                    ),
                    "images": [image_b64],
                }],
                "think": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": min(
                        _int_arg(args.get("max_tokens"), 1200, min_value=128, max_value=3000),
                        900 if label == "Весь лист" else 550,
                    ),
                },
                "stream": False,
            }
            response = httpx.post(f"{base_url}/api/chat", json=body, timeout=180.0)
            response.raise_for_status()
            data = response.json()
            item = str((data.get("message") or {}).get("content") or "").strip()
            if item:
                observations.append(f"{label}:\n{item}")
        observation = "\n\n".join(observations)
    except Exception as exc:  # noqa: BLE001
        return _result(tool="look_at_pdf_page", operation="vision_read", inputs=[args], status="error",
                       result={"model": model}, warnings=[str(exc)[:240]], trace=f"vision request failed: {type(exc).__name__}")
    source_ref = f"{document.get('file_name') or source_path.name}#page={page_number}"
    return _result(
        tool="look_at_pdf_page", operation="vision_read",
        inputs=[{"doc_id": document.get("id"), "page": page_number, "question": question, "bbox": args.get("bbox") or []}],
        status="ok" if observation else "missing",
        result={
            "observation": observation,
            "model": model,
            "source_ref": source_ref,
            "page": page_number,
            "text_layer_excerpt": page_text[:12000],
        },
        evidence=[{"kind": "visual_pdf_page", "source_ref": source_ref, "is_evidence": True}],
        sources=[{"kind": "pdf_page", "doc_id": document.get("id"), "doc_name": document.get("file_name"), "page": page_number, "source_ref": source_ref}],
        missing=[] if observation else ["vision model returned no observation"],
        trace="rendered one bounded original PDF page and inspected its pixels with the configured local vision model",
    )


def _tool_read_excel_source(args: dict[str, Any]) -> dict[str, Any]:
    payload = _read_source_payload("read_excel_source", args)
    doc_name = _result_doc_name(payload)
    warnings = list(payload.get("warnings") or [])
    if doc_name and Path(doc_name).suffix.casefold() not in _EXCEL_EXT:
        warnings.append("source extension is not excel/csv-like")
    warnings.append("raw sheet/range extraction is not part of this first tool pass; using indexed chunks")
    payload["warnings"] = list(dict.fromkeys(warnings))
    payload["trace"] = str(payload.get("trace") or "") + "; excel indexed-chunk read"
    if isinstance(payload.get("tool_trace"), dict):
        payload["tool_trace"]["warnings"] = payload["warnings"]
        payload["tool_trace"]["trace"] = payload["trace"]
    payload["contract_check"] = validate_tool_result(payload)
    return payload


def _tool_search_project_tables(args: dict[str, Any]) -> dict[str, Any]:
    from proxy.services.project_table_registry_service import search_project_tables

    dataset_id = str(args.get("dataset_id") or "").strip()
    q = str(args.get("q") or "").strip()
    semantic_type = str(args.get("semantic_type") or "").strip()
    file_filter = str(args.get("file") or "").strip()
    if not dataset_id:
        return _result(tool="search_project_tables", operation="search", inputs=[args], status="missing",
                       result={}, missing=["dataset_id"], trace="dataset_id is required")
    if not (q or semantic_type or file_filter):
        return _result(tool="search_project_tables", operation="search", inputs=[args], status="missing",
                       result={}, missing=["q, semantic_type or file"], trace="table selector is required")
    result = search_project_tables(
        dataset_id,
        q,
        semantic_type=semantic_type,
        file_filter=file_filter,
        limit=_int_arg(args.get("limit"), 20, min_value=1, max_value=100),
        storage_root=Path(str(args.get("storage_root") or "storage/datasets")),
    )
    items = result.get("items") or []
    return _result(
        tool="search_project_tables",
        operation="search",
        inputs=[{"dataset_id": dataset_id, "q": q, "semantic_type": semantic_type, "file": file_filter}],
        status="ok" if items else "missing",
        result=result,
        evidence=[{"kind": "navigation", "dataset_id": dataset_id, "is_evidence": False}],
        sources=[{"kind": "project_table_card", "table_id": item.get("table_id"), "source_ref": item.get("source_ref")} for item in items],
        missing=[] if items else ["no project tables matched selector"],
        trace="searched Л.И.С.Т. table registry; cards are navigation, not evidence",
    )


def _tool_read_project_table(args: dict[str, Any]) -> dict[str, Any]:
    from proxy.services.project_table_registry_service import read_project_table

    dataset_id = str(args.get("dataset_id") or "").strip()
    table_id = str(args.get("table_id") or "").strip()
    if not dataset_id or not table_id:
        return _result(tool="read_project_table", operation="read", inputs=[args], status="missing",
                       result={}, missing=["dataset_id and table_id"], trace="table selector is required")
    try:
        result = read_project_table(
            dataset_id,
            table_id,
            max_rows=_int_arg(args.get("max_rows"), 100, min_value=1, max_value=500),
            storage_root=Path(str(args.get("storage_root") or "storage/datasets")),
        )
    except (KeyError, ValueError, FileNotFoundError) as exc:
        return _result(tool="read_project_table", operation="read", inputs=[args], status="missing",
                       result={}, missing=[str(exc)], trace="project table could not be read")
    if result.get("status") == "stale":
        return _result(
            tool="read_project_table",
            operation="read",
            inputs=[{"dataset_id": dataset_id, "table_id": table_id}],
            status="blocked",
            result=result,
            evidence=[],
            sources=[{"kind": "project_pdf_table", "source_ref": result.get("source_ref")}],
            missing=[f"stale table evidence: {result.get('reason') or 'registry rebuild required'}"],
            trace="refused stale project table; rebuild registry before exact read",
        )
    return _result(
        tool="read_project_table",
        operation="read",
        inputs=[{"dataset_id": dataset_id, "table_id": table_id}],
        status="ok" if result.get("matrix") else "missing",
        result=result,
        evidence=[{"kind": "project_pdf_table", "source_ref": result.get("source_ref"), "is_evidence": True}],
        sources=[{"kind": "project_pdf_table", "source_ref": result.get("source_ref"), "source_path": result.get("source_path")}],
        missing=[] if result.get("matrix") else ["table has no readable rows"],
        trace="read exact bounded rows from original project PDF table",
    )


def _tool_assemble_project_volume(args: dict[str, Any]) -> dict[str, Any]:
    from proxy.services.project_document_registry_service import assemble_virtual_volume

    dataset_id = str(args.get("dataset_id") or "").strip()
    index = str(args.get("index") or "").strip()
    if not dataset_id or not index:
        return _result(tool="assemble_project_volume", operation="select", inputs=[args], status="missing",
                       result={}, missing=["dataset_id and index"], trace="volume selector is required")
    result = assemble_virtual_volume(
        dataset_id,
        index,
        storage_root=Path(str(args.get("storage_root") or "storage/datasets")),
    )
    ok = result.get("status") not in {"missing", "error"}
    return _result(
        tool="assemble_project_volume",
        operation="select",
        inputs=[{"dataset_id": dataset_id, "index": index}],
        status="ok" if ok else "missing",
        result=result,
        evidence=[{"kind": "navigation", "dataset_id": dataset_id, "is_evidence": False}],
        missing=list(result.get("missing") or []),
        trace="selected metadata-only virtual volume; no files were merged",
    )


def _read_source_payload(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    doc_id = str(args.get("doc_id") or "").strip()
    q = str(args.get("q") or "").strip()
    limit = _int_arg(args.get("limit"), 80, min_value=1, max_value=500)
    max_chars = _int_arg(args.get("max_chars"), 4000, min_value=200, max_value=12000)
    if doc_id:
        result = explorer().document_chunks_by_id(doc_id, q=q, limit=limit, max_chars=max_chars)
        if result is None:
            return _result(tool=tool, operation="read", inputs=[args], status="missing",
                           result={}, missing=[f"document not found: {doc_id}"], trace="doc_id lookup returned no document")
    else:
        dataset_id = str(args.get("dataset_id") or "").strip()
        doc_name = str(args.get("doc_name") or "").strip()
        if not dataset_id or not doc_name:
            return _result(tool=tool, operation="read", inputs=[args], status="missing",
                           result={}, missing=["doc_id or dataset_id+doc_name"], trace="document selector is required")
        result = explorer().document_chunks(dataset_id, doc_name, q=q, limit=limit, max_chars=max_chars)
    rows = result.get("hits") or result.get("chunks") or []
    return _result(
        tool=tool,
        operation="read",
        inputs=[{"doc_id": doc_id, "dataset_id": args.get("dataset_id") or "", "doc_name": args.get("doc_name") or "", "q": q}],
        status="ok" if rows else "missing",
        result=result,
        sources=_sources_from_rows(rows),
        missing=[] if rows else ["document has no indexed chunks for this selector"],
        warnings=[str(result.get("warning"))] if isinstance(result, dict) and result.get("warning") else [],
        trace="read indexed document chunks through DocumentExplorer",
    )


def _tool_filesystem_roots(args: dict[str, Any]) -> dict[str, Any]:
    roots = _allowed_roots()
    result = {
        "roots": [
            {"key": key, "path": str(path), "exists": path.exists(), "read_only": True}
            for key, path in roots.items()
        ],
        "forbidden_parts": sorted(_FORBIDDEN_PARTS),
    }
    return _result(tool="filesystem_roots", operation="list_roots", inputs=[{}], status="ok",
                   result=result, trace="listed whitelist filesystem roots")


def _tool_web_search(args: dict[str, Any]) -> dict[str, Any]:
    from proxy.services.web_search_service import search_web

    query = str(args.get("q") or "").strip()
    limit = _int_arg(args.get("limit"), 8, min_value=1, max_value=12)
    payload = search_web(query, limit=limit)
    rows = list(payload.get("results") or [])
    sources = [
        {"kind": "web", "url": row.get("url"), "title": row.get("title"), "domain": row.get("domain")}
        for row in rows
    ]
    return _result(
        tool="web_search",
        operation="search",
        inputs=[{"q": query, "limit": limit}],
        status=str(payload.get("status") or "missing"),
        result={"query": payload.get("query") or query, "results": rows},
        sources=sources,
        missing=list(payload.get("missing") or []),
        trace=f"searched public web; returned {len(rows)} bounded result(s)",
    )


def _tool_filesystem_list(args: dict[str, Any]) -> dict[str, Any]:
    root_key = str(args.get("root") or "docs")
    target = _safe_path(root_key, str(args.get("path") or ""))
    if not target.exists():
        return _result(tool="filesystem_list", operation="list", inputs=[_redact_args(args)], status="missing",
                       result={}, missing=[f"path not found: {args.get('path') or ''}"], trace="filesystem path not found")
    depth = _int_arg(args.get("depth"), 1, min_value=0, max_value=4)
    result = _fs_node(root_key, target, depth=depth)
    return _result(tool="filesystem_list", operation="list", inputs=[_redact_args(args)], status="ok",
                   result=result, sources=[_fs_source(root_key, target)], trace="listed whitelisted filesystem path")


def _tool_filesystem_stat(args: dict[str, Any]) -> dict[str, Any]:
    root_key = str(args.get("root") or "docs")
    target = _safe_path(root_key, str(args.get("path") or ""))
    if not target.exists():
        return _result(tool="filesystem_stat", operation="stat", inputs=[_redact_args(args)], status="missing",
                       result={}, missing=[f"path not found: {args.get('path') or ''}"], trace="filesystem path not found")
    return _result(tool="filesystem_stat", operation="stat", inputs=[_redact_args(args)], status="ok",
                   result=_fs_metadata(root_key, target), sources=[_fs_source(root_key, target)],
                   trace="read filesystem metadata")


def _tool_filesystem_read_text(args: dict[str, Any]) -> dict[str, Any]:
    root_key = str(args.get("root") or "docs")
    target = _safe_path(root_key, str(args.get("path") or ""))
    if not target.is_file():
        return _result(tool="filesystem_read_text", operation="read_text", inputs=[_redact_args(args)], status="missing",
                       result={}, missing=["file not found"], trace="filesystem file not found")
    if target.suffix.casefold() not in _TEXT_EXT:
        return _result(tool="filesystem_read_text", operation="read_text", inputs=[_redact_args(args)], status="missing",
                       result={}, missing=["not a supported text file"], trace="binary or unsupported text extension")
    size = target.stat().st_size
    if size > _MAX_TEXT_BYTES:
        return _result(tool="filesystem_read_text", operation="read_text", inputs=[_redact_args(args)], status="missing",
                       result={}, missing=["file too large for text tool"], trace="text file exceeds safety limit")
    max_chars = _int_arg(args.get("max_chars"), 20000, min_value=200, max_value=100000)
    text = target.read_text(encoding="utf-8", errors="replace")
    result = _fs_metadata(root_key, target) | {"text": text[:max_chars], "text_truncated": len(text) > max_chars}
    return _result(tool="filesystem_read_text", operation="read_text", inputs=[_redact_args(args)], status="ok",
                   result=result, sources=[_fs_source(root_key, target)], trace="read whitelisted text file")


def _tool_filesystem_search(args: dict[str, Any]) -> dict[str, Any]:
    q = str(args.get("q") or "").strip()
    if not q:
        return _result(tool="filesystem_search", operation="search", inputs=[_redact_args(args)], status="missing",
                       result={}, missing=["q"], trace="query is required")
    root_key = str(args.get("root") or "docs")
    base = _safe_path(root_key, str(args.get("path") or ""))
    if not base.exists():
        return _result(tool="filesystem_search", operation="search", inputs=[_redact_args(args)], status="missing",
                       result={}, missing=["path not found"], trace="filesystem search base not found")
    limit = _int_arg(args.get("limit"), 50, min_value=1, max_value=200)
    include_content = bool(args.get("content"))
    hits = _fs_search(root_key, base, q=q, include_content=include_content, limit=limit)
    return _result(
        tool="filesystem_search",
        operation="search",
        inputs=[_redact_args(args)],
        status="ok" if hits else "missing",
        result={"query": q, "hits": hits, "count": len(hits), "content": include_content},
        sources=[_fs_source(root_key, base)],
        missing=[] if hits else ["no files matched query"],
        trace="searched whitelisted filesystem path",
    )


def _tool_filesystem_hash(args: dict[str, Any]) -> dict[str, Any]:
    root_key = str(args.get("root") or "docs")
    target = _safe_path(root_key, str(args.get("path") or ""))
    if not target.is_file():
        return _result(tool="filesystem_hash", operation="hash", inputs=[_redact_args(args)], status="missing",
                       result={}, missing=["file not found"], trace="hash target is not a file")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    result = _fs_metadata(root_key, target) | {"sha256": digest}
    return _result(tool="filesystem_hash", operation="hash", inputs=[_redact_args(args)], status="ok",
                   result=result, sources=[_fs_source(root_key, target)], trace="calculated sha256 for whitelisted file")


def _allowed_roots() -> dict[str, Path]:
    roots: dict[str, Path] = {
        "docs": (_REPO_ROOT / "docs").resolve(),
        "storage_datasets": (_REPO_ROOT / "storage" / "datasets").resolve(),
        "rag_content": (_REPO_ROOT / "RAG_Content").resolve(),
        "artifacts": (_REPO_ROOT / "storage" / "artifacts").resolve(),
    }
    raw = os.getenv("LES_TOOL_FS_EXTRA_ROOTS", "")
    for item in (part.strip() for part in raw.split(",")):
        if not item:
            continue
        if "=" in item:
            key, value = item.split("=", 1)
        else:
            value = item
            key = Path(value).name or "extra"
        key = re.sub(r"[^0-9A-Za-z_-]+", "_", key.strip())[:40] or "extra"
        roots[key] = Path(value).expanduser().resolve()
    return roots


def _safe_path(root_key: str, rel_path: str) -> Path:
    roots = _allowed_roots()
    if root_key not in roots:
        raise ValueError(f"unknown filesystem root: {root_key}")
    clean_parts = [part for part in Path(rel_path or "").parts if part not in ("", ".")]
    if any(part == ".." or part.startswith(".") or part in _FORBIDDEN_PARTS for part in clean_parts):
        raise ValueError("filesystem path contains a forbidden segment")
    root = roots[root_key]
    target = (root / Path(*clean_parts)).resolve() if clean_parts else root
    if target != root and root not in target.parents:
        raise ValueError("filesystem path escapes allowed root")
    if any(part in _FORBIDDEN_PARTS for part in target.parts):
        raise ValueError("filesystem path crosses a forbidden directory")
    return target


def _fs_node(root_key: str, path: Path, *, depth: int) -> dict[str, Any]:
    meta = _fs_metadata(root_key, path)
    if path.is_dir() and depth > 0:
        children: list[dict[str, Any]] = []
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
        except OSError:
            entries = []
        for child in entries:
            if child.name.startswith(".") or child.name in _FORBIDDEN_PARTS:
                continue
            children.append(_fs_node(root_key, child, depth=depth - 1))
            if len(children) >= 500:
                break
        meta["children"] = children
    return meta


def _fs_metadata(root_key: str, path: Path) -> dict[str, Any]:
    root = _allowed_roots()[root_key]
    rel = "" if path == root else str(path.relative_to(root))
    stat = path.stat()
    return {
        "root": root_key,
        "path": rel,
        "name": path.name or root_key,
        "is_dir": path.is_dir(),
        "is_file": path.is_file(),
        "suffix": path.suffix,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
    }


def _fs_search(root_key: str, base: Path, *, q: str, include_content: bool, limit: int) -> list[dict[str, Any]]:
    needle = q.casefold()
    hits: list[dict[str, Any]] = []
    stack = [base]
    visited = 0
    while stack and len(hits) < limit and visited < 5000:
        current = stack.pop()
        visited += 1
        try:
            meta = _fs_metadata(root_key, current)
        except OSError:
            continue
        name_hit = needle in current.name.casefold()
        content_snippet = ""
        if include_content and current.is_file() and current.suffix.casefold() in _TEXT_EXT:
            try:
                if current.stat().st_size <= 200_000:
                    text = current.read_text(encoding="utf-8", errors="replace")
                    pos = text.casefold().find(needle)
                    if pos >= 0:
                        start = max(0, pos - 120)
                        end = min(len(text), pos + len(q) + 120)
                        content_snippet = text[start:end].strip()
            except OSError:
                content_snippet = ""
        if name_hit or content_snippet:
            hit = meta | {"match": "content" if content_snippet else "name"}
            if content_snippet:
                hit["snippet"] = content_snippet
            hits.append(hit)
        if current.is_dir():
            try:
                children = sorted(current.iterdir(), key=lambda p: p.name.casefold(), reverse=True)
            except OSError:
                children = []
            for child in children:
                if child.name.startswith(".") or child.name in _FORBIDDEN_PARTS:
                    continue
                stack.append(child)
    return hits


def _result(
    *,
    tool: str,
    operation: str,
    inputs: list[Any],
    status: str,
    result: Any,
    trace: str,
    evidence: list[dict[str, Any]] | None = None,
    sources: list[dict[str, Any]] | None = None,
    missing: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    warnings = list(warnings or [])
    trace_obj = make_tool_trace(
        tool=tool,
        operation=operation,
        inputs=inputs,
        result=result,
        trace=trace,
        status=status,
        warnings=warnings,
        decision_required_from_model=True,
        source="les_tool_harness",
    ).to_dict()
    payload = {
        "schema": TOOL_RESULT_SCHEMA,
        "tool": tool,
        "operation": operation,
        "inputs": inputs,
        "status": status,
        "result": result,
        "evidence": list(evidence or []),
        "sources": list(sources or []),
        "missing": list(missing or []),
        "warnings": warnings,
        "trace": trace,
        "tool_trace": trace_obj,
        "decision_required_from_model": True,
    }
    payload["contract_check"] = validate_tool_result(payload)
    return payload


def _sources_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (str(row.get("dataset_id") or ""), str(row.get("doc_name") or ""), str(row.get("chunk_ord") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "kind": "indexed_chunk",
                "dataset_id": row.get("dataset_id"),
                "doc_id": row.get("doc_id"),
                "doc_name": row.get("doc_name"),
                "chunk_ord": row.get("chunk_ord"),
                "point_id": row.get("point_id"),
                "section_heading": row.get("section_heading") or row.get("parent_heading") or "",
            }
        )
    return out


def _result_doc_name(payload: dict[str, Any]) -> str:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    document = result.get("document") if isinstance(result.get("document"), dict) else {}
    return str(document.get("file_name") or result.get("doc_name") or "")


def _fs_source(root_key: str, path: Path) -> dict[str, Any]:
    meta = _fs_metadata(root_key, path)
    return {"kind": "filesystem", "root": root_key, "path": meta["path"], "name": meta["name"]}


def _list_arg(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _int_arg(value: Any, default: int, *, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[0-9A-Za-zА-Яа-яЁё_.-]{3,}", text)}


def _redact_args(args: dict[str, Any]) -> dict[str, Any]:
    redacted = {}
    for key, value in args.items():
        if "secret" in key.casefold() or "password" in key.casefold() or "token" in key.casefold():
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted


def harness() -> ToolHarness:
    return ToolHarness()
