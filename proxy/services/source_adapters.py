"""Unified Construction Harness v0.9 — real source adapters (unavailable-safe, без фейков).

Превращает размытые limitation'ы (parquet_only / lexical_miss / qdrant_not_used / mail_source_missing)
в ЯВНЫЕ adapter-статусы с source_kind и searched_tiers. Адаптеры оборачивают РЕАЛЬНЫЕ сервисы:
- lexical: LexicalIndex (sync SQLite/FTS) — реально находит, если индекс есть;
- vector: Qdrant/retrieval — async+backend, в sync/offline → unavailable (НЕ фейк);
- mail: mail_query — async+backend, без него → unavailable/not_configured (НЕ фейк).

Инвариант: нет реального source_ref → не RETRIEVED; backend недоступен → warning+unavailable, не выдумка.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

# статусы и source_kind
FOUND, NOT_FOUND, NO_SCOPE, UNAVAILABLE, ERROR = "found", "not_found", "no_scope", "unavailable", "error"
TIMEOUT, NO_SOURCE, WEAK_RELATED = "timeout", "no_source", "weak_related"
KIND_PARQUET = "parquet_row"
KIND_FILENAME = "filename_metadata"
KIND_LEXICAL = "lexical_chunk"
KIND_VECTOR = "vector_chunk"
KIND_MAIL = "mail_message"
KIND_WORKBOOK = "workbook_cell"
KIND_FILE_BODY = "file_body"           # v0.12: тело .md/.txt
KIND_EML = "mail_message"              # .eml = mail_message kind

# v0.12 file_body limits (read-only, без OCR/бинарей)
_TEXT_EXTS = {".md", ".txt", ".csv"}
_MAX_FILE_BYTES = 8 * 1024 * 1024
_MAX_FILES_PER_QUERY = 400
_MAX_SNIPPETS_PER_FILE = 3


@dataclass
class AdapterMatch:
    source_kind: str
    source_ref: str
    file_name: str = ""
    dataset_id: str = ""
    snippet: str = ""
    chunk_id: str = ""
    page: int | None = None
    row_id: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    score: float | None = None
    matched_term: str = ""
    fields: dict = field(default_factory=dict)   # mail: from/to/date/subject


@dataclass
class SourceAdapterResult:
    status: str                       # found|not_found|no_scope|unavailable|error
    source_kind: str = "unknown"
    matches: list[AdapterMatch] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)

    @property
    def source_refs(self) -> list[str]:
        return [m.source_ref for m in self.matches]


def _norm(s: Any) -> str:
    return re.sub(r"[\s.\-_]", "", str(s)).lower()


# ── lexical adapter (sync SQLite/FTS — реально закрывает parquet_only/lexical_miss) ───────

def search_lexical_chunks(query_terms: list[str], *, dataset_ids: list[str] | None = None,
                          doc_type_filter: set[str] | None = None, top_k: int = 8) -> SourceAdapterResult:
    """Поиск термина в lexical-чанках (тело PDF/доков, если проиндексировано). source-scoped exact:
    оставляем только чанки, где термин реально встречается, и (если задан) нужного doc_type."""
    if not query_terms:
        return SourceAdapterResult(NOT_FOUND, KIND_LEXICAL, warnings=["нет термина для поиска"])
    try:
        from proxy.services.lexical_index_service import LexicalIndex, lexical_enabled
        from backend.rag_config import rag_collection_name
        if not lexical_enabled():
            return SourceAdapterResult(UNAVAILABLE, KIND_LEXICAL,
                                       warnings=["lexical_unavailable: lexical-индекс выключен"])
        idx = LexicalIndex()
        chunks = idx.search(" ".join(query_terms), collection=rag_collection_name(),
                            dataset_ids=dataset_ids or None, limit=top_k * 3)
    except Exception as e:  # noqa: BLE001
        return SourceAdapterResult(UNAVAILABLE, KIND_LEXICAL,
                                   warnings=[f"lexical_unavailable: {str(e)[:80]}"])
    terms_norm = [_norm(t) for t in query_terms if _norm(t)]
    matches: list[AdapterMatch] = []
    for c in chunks:
        text = getattr(c, "text", "") or getattr(c, "content", "") or ""
        doc = str(getattr(c, "doc_name", "") or "")
        if doc_type_filter:
            from proxy.services.unified_construction_harness_service import classify_doc_type
            if classify_doc_type(doc) not in doc_type_filter:
                continue
        tnorm = _norm(text)
        hit = next((qt for qt in terms_norm if qt and qt in tnorm), None)
        if not hit:
            continue
        ds = str(getattr(c, "dataset_id", "") or "")
        ord_ = getattr(c, "chunk_ord", None)
        ref = f"{ds}/{doc}#chunk{ord_}" if ord_ is not None else f"{ds}/{doc}#chunk"
        matches.append(AdapterMatch(KIND_LEXICAL, ref, file_name=doc, dataset_id=ds,
                                    snippet=text[:200], chunk_id=str(ord_), matched_term=hit,
                                    score=getattr(c, "score", None)))
        if len(matches) >= top_k:
            break
    status = FOUND if matches else NOT_FOUND
    return SourceAdapterResult(status, KIND_LEXICAL, matches=matches,
                               trace=[{"adapter": "lexical", "chunks_scanned": len(chunks), "matches": len(matches)}])


# ── vector adapter (Qdrant/retrieval — async+backend → unavailable в sync/offline) ────────

def search_vector_chunks(question: str, *, dataset_ids: list[str] | None = None,
                         doc_type_filter: set[str] | None = None, top_k: int = 6) -> SourceAdapterResult:
    """Векторный (Qdrant) поиск. Требует async rag_backend; в sync unified-пути/offline → UNAVAILABLE
    с явным warning (НЕ фейк). Реальная интеграция — когда backend подключён в sync-обёртке."""
    try:
        from proxy.routers.chat import get_chat_state
        state = get_chat_state()
        backend = getattr(state, "backend", None)
    except Exception:  # noqa: BLE001
        backend = None
    if backend is None or not hasattr(backend, "query_points") and not hasattr(backend, "search"):
        return SourceAdapterResult(UNAVAILABLE, KIND_VECTOR, warnings=[
            "vector_unavailable: Qdrant/vector backend не подключён к sync unified-пути"])
    # backend есть, но retrieve_chat_chunks асинхронный — в sync-обёртке не вызываем (честно unavailable)
    return SourceAdapterResult(UNAVAILABLE, KIND_VECTOR, warnings=[
        "vector_unavailable: vector-ретрив асинхронный, не вшит в sync unified-путь (v0.9 deferred)"])


# ── mail adapter (read-only; async mail_query+backend → unavailable/not_configured) ───────

def retrieve_mail_evidence(query_terms: list[str], *, project_id: int = 0,
                           dataset_ids: list[str] | None = None) -> SourceAdapterResult:
    """Read-only поиск по почте. Существующий mail_query асинхронный и требует rag_backend +
    mail-dataset. Без них → UNAVAILABLE (mail_backend_not_configured). НИКАКИХ send/push/mutate."""
    try:
        from proxy.routers.chat import get_chat_state
        state = get_chat_state()
        backend = getattr(state, "backend", None)
    except Exception:  # noqa: BLE001
        backend = None
    if backend is None or not hasattr(backend, "list_datasets"):
        return SourceAdapterResult(UNAVAILABLE, KIND_MAIL, warnings=[
            "mail_backend_not_configured: почтовый backend (rag_backend + mail-dataset) не подключён"])
    # backend есть, но maybe_answer_mail_query асинхронный — в sync-пути не вызываем (честно unavailable)
    return SourceAdapterResult(UNAVAILABLE, KIND_MAIL, warnings=[
        "mail_backend_not_configured: async mail_query не вшит в sync unified-путь (v0.9 deferred)"])


# ── v0.10: async-адаптеры (вызываются из _run_chat через инжектированные замыкания) ───────
# Адаптер НЕ знает тяжёлую сигнатуру retrieve_chat_chunks/mail_query — caller передаёт готовую
# async-функцию. Адаптер делает timeout/error→статус и требует source_ref. БЕЗ фейков.

VectorFn = Callable[[str, "list[str] | None"], Awaitable[Any]]
MailFn = Callable[[str], Awaitable[Any]]


def _chunk_ref(c: Any) -> tuple[str, str, str, str]:
    ds = str(getattr(c, "dataset_id", "") or (getattr(c, "meta", {}) or {}).get("dataset_id", "") or "")
    doc = str(getattr(c, "doc_name", "") or (getattr(c, "meta", {}) or {}).get("file_name", "") or "")
    ord_ = getattr(c, "chunk_ord", None)
    if ord_ is None:
        ord_ = (getattr(c, "meta", {}) or {}).get("chunk_ord")
    text = getattr(c, "text", "") or getattr(c, "content", "") or ""
    ref = f"{ds}/{doc}#chunk{ord_}" if ord_ is not None else (f"{ds}/{doc}#vec" if doc else "")
    return ds, doc, str(ord_), ref, text  # type: ignore[return-value]


async def search_vector_chunks_async(question: str, *, dataset_ids: list[str] | None = None,
                                     doc_type_filter: set[str] | None = None,
                                     exact_terms: list[str] | None = None,
                                     vector_fn: VectorFn | None = None,
                                     require_exact: bool = False,
                                     timeout_s: float = 8.0) -> SourceAdapterResult:
    """Векторный (Qdrant/RAG) поиск через инжектированный vector_fn. Нет fn → unavailable.
    require_exact: для source-scoped exact — матч только если термин реально в сниппете; иначе
    weak_related (НЕ выдаём семантический матч за точное вхождение). Источник без ref → не RETRIEVED."""
    if vector_fn is None:
        return SourceAdapterResult(UNAVAILABLE, KIND_VECTOR,
                                   warnings=["vector_backend_unavailable: vector-retrieval не подключён"])
    try:
        chunks = await asyncio.wait_for(vector_fn(question, dataset_ids), timeout_s)
    except asyncio.TimeoutError:
        return SourceAdapterResult(TIMEOUT, KIND_VECTOR, warnings=["vector_timeout: превышен лимит ответа"])
    except Exception as e:  # noqa: BLE001
        return SourceAdapterResult(ERROR, KIND_VECTOR, warnings=[f"vector_error: {str(e)[:80]}"])
    chunks = list(chunks or [])
    terms_norm = [_norm(t) for t in (exact_terms or []) if _norm(t)]
    matches, weak = [], 0
    for c in chunks:
        ds, doc, ord_, ref, text = _chunk_ref(c)
        if not ref:
            continue                                   # нет source_ref → не RETRIEVED (не фейк)
        if doc_type_filter and doc:
            from proxy.services.unified_construction_harness_service import classify_doc_type
            if classify_doc_type(doc) not in doc_type_filter:
                continue
        is_exact = (not terms_norm) or any(t in _norm(text) for t in terms_norm)
        if require_exact and not is_exact:
            weak += 1
            continue                                   # семантический без термина → weak, не found
        matches.append(AdapterMatch(KIND_VECTOR, ref, file_name=doc, dataset_id=ds, snippet=text[:200],
                                    chunk_id=ord_, score=getattr(c, "score", None),
                                    matched_term=(exact_terms[0] if terms_norm and is_exact else "")))
    if matches:
        return SourceAdapterResult(FOUND, KIND_VECTOR, matches=matches,
                                   trace=[{"adapter": "vector", "chunks": len(chunks), "matches": len(matches)}])
    status = WEAK_RELATED if weak else NOT_FOUND
    w = ["vector: семантически близкие документы есть, но точного термина нет (weak_related)"] if weak else []
    return SourceAdapterResult(status, KIND_VECTOR, warnings=w,
                               trace=[{"adapter": "vector", "chunks": len(chunks), "weak": weak}])


def inspect_dataset_index_health(dataset_ids: list[str], *, storage_root: Any = None) -> dict[str, Any]:
    """v0.11 диагностика: чем РЕАЛЬНО наполнен датасет (parquet/файлы/lexical/mail/doc-типы). Превращает
    общий lexical_miss в конкретный no_lexical_index/no_parquet. Без дорогих сканов (только count)."""
    from pathlib import Path as _P
    from collections import Counter
    root = _P(storage_root) if storage_root else _P("storage/datasets")
    # lexical-счётчик по датасету (если индекс есть)
    lex_counts: dict[str, int] = {}
    try:
        from proxy.services.lexical_index_service import LexicalIndex, lexical_enabled
        if lexical_enabled():
            idx = LexicalIndex()
            with idx.connect() as conn:
                for ds in dataset_ids:
                    try:
                        lex_counts[ds] = conn.execute(
                            "SELECT count(*) FROM lexical_chunks WHERE dataset_id=?", (ds,)).fetchone()[0]
                    except Exception:  # noqa: BLE001
                        lex_counts[ds] = -1
    except Exception:  # noqa: BLE001
        lex_counts = {}
    out = []
    from proxy.services.doc_extract_service import (sidecar_count as _sidecar_count, read_sidecars,
                                                    SIDECAR_DIRNAME, read_manifest, sidecar_stale_files)
    for ds in dataset_ids:
        ddir = root / ds
        parquet = files = mail = md = txt = eml = md_tables = pdf = docx = xlsx = 0
        doc_types: Counter = Counter()
        if ddir.exists():
            from proxy.services.unified_construction_harness_service import classify_doc_type
            for p in ddir.rglob("*"):
                if not p.is_file() or p.name.startswith(".") or f"/{SIDECAR_DIRNAME}/" in p.as_posix():
                    continue
                ext = p.suffix.lower()
                if ext == ".parquet":
                    parquet += 1
                else:
                    files += 1
                    if ext == ".eml":
                        mail += 1; eml += 1
                    elif ext == ".md":
                        md += 1
                        if md_tables < 50:
                            md_tables += len(extract_markdown_tables_from_file(p))
                    elif ext == ".txt":
                        txt += 1
                    elif ext == ".pdf":
                        pdf += 1
                    elif ext == ".docx":
                        docx += 1
                    elif ext == ".xlsx":
                        xlsx += 1
                    doc_types[classify_doc_type(p.name)] += 1
        scount = _sidecar_count(root, ds)
        ext_items = read_sidecars(root, ds) if scount else []
        extracted_body = len(ext_items)
        manifest_present = read_manifest(root, ds) is not None
        stale = sidecar_stale_files(root, ds) if manifest_present else []
        lex = lex_counts.get(ds, 0 if lex_counts else None)
        readable_body = (md + txt) > 0
        binary_docs = pdf + docx + xlsx
        warns = []
        warns.append("no_parquet_but_markdown_table_found" if (parquet == 0 and md_tables) else "no_parquet"
                     if parquet == 0 else "")
        if lex is not None and lex <= 0:
            warns.append("no_lexical_index_but_file_body_available" if (readable_body or extracted_body)
                         else "no_lexical_index")
        elif lex is None:
            warns.append("lexical_unavailable")
        # v0.13: бинарные доки есть, но sidecar не создан → конкретная причина + actionable
        if binary_docs and extracted_body == 0:
            if pdf:
                warns.append("pdf_files_without_sidecars")
            if docx:
                warns.append("docx_files_without_sidecars")
            if xlsx:
                warns.append("xlsx_files_without_sidecars")
            warns.append("no_extracted_body")
        if eml == 0:
            warns.append("no_eml_messages")
        if files == 0 and parquet == 0:
            warns.append("empty_dataset")
        if not readable_body and not extracted_body and eml == 0 and binary_docs == 0:
            warns.append("no_file_body_readable")
        if stale:
            warns.append("sidecar_stale")
        warns = [w for w in warns if w]
        out.append({"dataset_id": ds, "parquet_count": parquet, "file_count": files, "mail_count": mail,
                    "md_file_count": md, "txt_file_count": txt, "eml_file_count": eml,
                    "pdf_file_count": pdf, "docx_file_count": docx, "xlsx_file_count": xlsx,
                    "sidecar_count": scount, "extracted_body_count": extracted_body,
                    "sidecar_available": extracted_body > 0, "manifest_present": manifest_present,
                    "stale_count": len(stale),
                    "readable_text_file_count": md + txt, "markdown_table_count": md_tables,
                    "readable_body_available": readable_body, "lexical_chunk_count": lex,
                    "doc_types": dict(doc_types), "warnings": warns})
    return {"datasets": out, "total_lexical_chunks": sum(v for v in lex_counts.values() if v and v > 0)}


async def retrieve_mail_evidence_async(query_terms: list[str], question: str = "", *,
                                       mail_fn: MailFn | None = None, timeout_s: float = 8.0) -> SourceAdapterResult:
    """Read-only поиск по почте через инжектированный mail_fn (обёртка maybe_answer_mail_query). Нет fn →
    mail_backend_not_configured. Только snippet (НЕ полное тело в trace). НИКАКИХ send/push/delete."""
    if mail_fn is None:
        return SourceAdapterResult(UNAVAILABLE, KIND_MAIL,
                                   warnings=["mail_backend_not_configured: почтовый backend не подключён"])
    try:
        res = await asyncio.wait_for(mail_fn(question or " ".join(query_terms)), timeout_s)
    except asyncio.TimeoutError:
        return SourceAdapterResult(TIMEOUT, KIND_MAIL, warnings=["mail_timeout: превышен лимит ответа"])
    except Exception as e:  # noqa: BLE001
        return SourceAdapterResult(ERROR, KIND_MAIL, warnings=[f"mail_error: {str(e)[:80]} (почта не изменялась)"])
    if res is None:
        return SourceAdapterResult(NOT_FOUND, KIND_MAIL, warnings=["mail: писем по запросу не найдено"])
    items = getattr(res, "items", None) or getattr(res, "messages", None) or []
    matches = []
    for m in items:
        get = (lambda k: m.get(k) if isinstance(m, dict) else getattr(m, k, None))
        mid = str(get("message_id") or get("id") or "")
        subj = str(get("subject") or "")
        ref = mid or (f"mail/{subj[:30]}" if subj else "")
        if not ref:
            continue                                   # нет message_id/source_ref → не RETRIEVED
        snippet = str(get("snippet") or get("preview") or "")[:200]   # ТОЛЬКО snippet, не полное тело
        matches.append(AdapterMatch(KIND_MAIL, ref, file_name=subj[:60], snippet=snippet, matched_term=mid))
    status = FOUND if matches else NOT_FOUND
    return SourceAdapterResult(status, KIND_MAIL, matches=matches,
                               trace=[{"adapter": "mail", "messages": len(matches)}])


# ── v0.12: file_body adapter (.md/.txt read-only, source_ref до строки) ──────────────────

def _safe_under(root, p) -> bool:
    from pathlib import Path as _P
    try:
        _P(p).resolve().relative_to(_P(root).resolve())
        return True
    except Exception:  # noqa: BLE001
        return False


def search_file_body(query_terms: list[str], *, dataset_ids: list[str] | None = None,
                     storage_root: Any = None, doc_type_filter: set[str] | None = None,
                     top_k: int = 12) -> SourceAdapterResult:
    """Прямой read-only поиск термина в теле .md/.txt/.csv (без lexical-индекса, без OCR/бинарей).
    source_ref до файла/строки. path-traversal защита + лимиты размера/числа файлов/сниппетов."""
    from pathlib import Path as _P
    if not query_terms:
        return SourceAdapterResult(NOT_FOUND, KIND_FILE_BODY, warnings=["нет термина"])
    if not dataset_ids:
        return SourceAdapterResult(NO_SCOPE, KIND_FILE_BODY, warnings=["нет dataset-scope"])
    root = _P(storage_root) if storage_root else _P("storage/datasets")
    terms_norm = [(_norm(t), t) for t in query_terms if _norm(t)]
    from proxy.services.unified_construction_harness_service import classify_doc_type
    matches: list[AdapterMatch] = []
    scanned = 0
    for ds in dataset_ids:
        ddir = root / ds
        if not ddir.exists():
            continue
        for p in sorted(ddir.rglob("*")):
            if scanned >= _MAX_FILES_PER_QUERY or len(matches) >= top_k:
                break
            if not p.is_file() or p.suffix.lower() not in _TEXT_EXTS or p.name.startswith("."):
                continue
            if not _safe_under(root, p):
                continue
            if doc_type_filter and classify_doc_type(p.name) not in doc_type_filter:
                continue
            try:
                if p.stat().st_size > _MAX_FILE_BYTES:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            scanned += 1
            if not any(tn in _norm(text) for tn, _ in terms_norm):
                continue
            rel = p.relative_to(ddir).as_posix()
            per_file = 0
            for i, ln in enumerate(text.splitlines(), 1):
                lnn = _norm(ln)
                hit = next((orig for tn, orig in terms_norm if tn and tn in lnn), None)
                if hit:
                    matches.append(AdapterMatch(KIND_FILE_BODY, f"{ds}/{rel}#L{i}", file_name=p.name,
                                                dataset_id=ds, snippet=ln.strip()[:200], line_start=i,
                                                line_end=i, matched_term=hit))
                    per_file += 1
                    if per_file >= _MAX_SNIPPETS_PER_FILE:
                        break
    status = FOUND if matches else NOT_FOUND
    return SourceAdapterResult(status, KIND_FILE_BODY, matches=matches,
                               trace=[{"adapter": "file_body", "files_scanned": scanned, "matches": len(matches)}])


# ── v0.12: eml adapter (.eml read-only, snippet-only, нет send/delete) ────────────────────

def _eml_plain_snippet(msg) -> str:
    try:
        body = msg.get_body(preferencelist=("plain",))
        if body is not None:
            return (body.get_content() or "")[:400]
    except Exception:  # noqa: BLE001
        pass
    return ""


def search_eml_messages(query_terms: list[str], *, dataset_ids: list[str] | None = None,
                        storage_root: Any = None, top_k: int = 12) -> SourceAdapterResult:
    """Read-only поиск термина в .eml (subject/body/attachment-names). Реальный mail-источник БЕЗ
    backend. snippet-only (полное тело НЕ в trace). НИКАКИХ send/draft/delete/mutate."""
    from pathlib import Path as _P
    from email import policy
    from email.parser import BytesParser
    if not dataset_ids:
        return SourceAdapterResult(NO_SCOPE, KIND_MAIL, warnings=["нет dataset-scope"])
    root = _P(storage_root) if storage_root else _P("storage/datasets")
    terms_norm = [_norm(t) for t in (query_terms or []) if _norm(t)]
    eml_seen = 0
    matches: list[AdapterMatch] = []
    for ds in dataset_ids:
        ddir = root / ds
        if not ddir.exists():
            continue
        for p in sorted(ddir.rglob("*.eml")):
            if len(matches) >= top_k:
                break
            if not _safe_under(root, p) or p.stat().st_size > _MAX_FILE_BYTES:
                continue
            eml_seen += 1
            try:
                with open(p, "rb") as fh:
                    msg = BytesParser(policy=policy.default).parse(fh)
            except Exception:  # noqa: BLE001
                continue
            subj = str(msg.get("subject", "") or "")
            frm = str(msg.get("from", "") or "")
            to = str(msg.get("to", "") or "")
            date = str(msg.get("date", "") or "")
            mid = str(msg.get("message-id", "") or "")
            body = _eml_plain_snippet(msg)
            atts = " ".join(part.get_filename() or "" for part in msg.iter_attachments()) if hasattr(msg, "iter_attachments") else ""
            hay = _norm(f"{subj} {body} {atts}")
            hit = next((t for t in terms_norm if t and t in hay), None) if terms_norm else "*"
            if not hit:
                continue
            ref = mid or f"{ds}/{p.relative_to(ddir).as_posix()}"
            matches.append(AdapterMatch(KIND_MAIL, ref, file_name=subj[:60], dataset_id=ds,
                                        snippet=(subj + " — " + body)[:200], matched_term=str(hit),
                                        fields={"from": frm[:80], "to": to[:80], "date": date[:40], "subject": subj[:120]}))
    if eml_seen == 0:
        return SourceAdapterResult(NO_SOURCE, KIND_MAIL, warnings=["no_eml_messages: .eml в датасете нет"])
    return SourceAdapterResult(FOUND if matches else NOT_FOUND, KIND_MAIL, matches=matches,
                               trace=[{"adapter": "eml", "eml_seen": eml_seen, "matches": len(matches)}])


# ── v0.12: markdown-таблицы → ВОР-строки ─────────────────────────────────────────────────

_MD_NAME = ("наименование", "работа", "вид работ", "позиция", "описание", "item", "name", "наимен")
_MD_UNIT = ("ед. изм", "ед.изм", "единица", "ед ", "изм", "unit", "ед")
_MD_QTY = ("кол-во", "количество", "кол", "объем", "объём", "qty", "к-во")


def extract_markdown_tables_from_file(path: Any) -> list[dict]:
    """Простые markdown pipe-таблицы (|...|...| + строка-разделитель |---|). source: line_start."""
    from pathlib import Path as _P
    p = _P(path)
    if not p.exists() or p.suffix.lower() not in (".md", ".txt"):
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:  # noqa: BLE001
        return []
    tables, i, n = [], 0, len(lines)
    while i < n - 1:
        if lines[i].strip().startswith("|") and set(lines[i + 1].strip().replace("|", "").replace(":", "").strip()) <= {"-", " "} and "-" in lines[i + 1]:
            header = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            rows, j = [], i + 2
            while j < n and lines[j].strip().startswith("|"):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")])
                j += 1
            tables.append({"header": header, "rows": rows, "line_start": i + 1, "line_end": j})
            i = j
        else:
            i += 1
    return tables


def _md_col(header: list[str], syns: tuple) -> int:
    for idx, h in enumerate(header):
        hl = h.lower()
        if any(s in hl for s in syns):
            return idx
    return -1


def markdown_table_to_rows(table: dict, *, file_name: str = "", dataset_id: str = "") -> dict:
    """Маппинг markdown-таблицы → ВОР-строки {name,unit,qty,source_file,pos}. Не распознано → blocked."""
    header = table["header"]
    ci_name = _md_col(header, _MD_NAME)
    ci_unit = _md_col(header, _MD_UNIT)
    ci_qty = _md_col(header, _MD_QTY)
    if ci_name < 0 or ci_qty < 0:
        return {"status": "not_recognized", "rows": [],
                "reason": "markdown_table_not_recognized: нет колонок наименование/кол-во"}
    rows = []
    base = f"{dataset_id}/{file_name}" if dataset_id else file_name
    for k, r in enumerate(table["rows"]):
        if max(ci_name, ci_qty, ci_unit) >= len(r):
            continue
        name = r[ci_name].strip()
        qty_raw = r[ci_qty].strip()
        unit = r[ci_unit].strip() if 0 <= ci_unit < len(r) else ""
        try:
            qty = float(qty_raw.replace(",", ".").replace(" ", "").replace(" ", ""))
        except ValueError:
            continue
        if not name:
            continue
        ln = table["line_end"] - len(table["rows"]) + k
        rows.append({"name": name, "unit": unit, "qty": qty,
                     "source_file": f"{base}#L{ln}", "pos": str(k + 1)})
    if not rows:
        return {"status": "missing_required_columns", "rows": [],
                "reason": "markdown_table_missing_required_columns: строки без name/qty"}
    return {"status": "ok", "rows": rows}


KIND_EXTRACTED = "extracted_body"   # v0.13: sidecar PDF/DOCX/XLSX


def search_extracted_body(query_terms: list[str], *, dataset_ids: list[str] | None = None,
                          storage_root: Any = None, doc_type_filter: set[str] | None = None,
                          top_k: int = 12) -> SourceAdapterResult:
    """v0.13: поиск термина в sidecar-извлечениях (PDF/DOCX/XLSX → _extracted/*.jsonl). source_ref до
    ОРИГИНАЛЬНОГО файла/страницы/абзаца/строки. Нет sidecar → not_found (actionable выше по стеку)."""
    from pathlib import Path as _P
    from proxy.services.doc_extract_service import read_sidecars
    if not query_terms:
        return SourceAdapterResult(NOT_FOUND, KIND_EXTRACTED, warnings=["нет термина"])
    if not dataset_ids:
        return SourceAdapterResult(NO_SCOPE, KIND_EXTRACTED, warnings=["нет dataset-scope"])
    root = _P(storage_root) if storage_root else _P("storage/datasets")
    terms_norm = [(_norm(t), t) for t in query_terms if _norm(t)]
    seen_any = False
    matches: list[AdapterMatch] = []
    for ds in dataset_ids:
        items = read_sidecars(root, ds)
        if items:
            seen_any = True
        if doc_type_filter:
            from proxy.services.unified_construction_harness_service import classify_doc_type
            items = [it for it in items if classify_doc_type(str(it.get("original_file_name", ""))) in doc_type_filter]
        for it in items:
            txt = str(it.get("text", ""))
            hit = next((orig for tn, orig in terms_norm if tn and tn in _norm(txt)), None)
            if not hit:
                continue
            ref = str(it.get("source_ref", ""))
            if not ref:
                continue                              # нет source_ref → не RETRIEVED
            matches.append(AdapterMatch(KIND_EXTRACTED, ref, file_name=str(it.get("original_file_name", "")),
                                        dataset_id=ds, snippet=txt[:200], matched_term=hit,
                                        page=it.get("page"), row_id=it.get("row_index"),
                                        line_start=it.get("paragraph_index"),
                                        fields={"source_kind": it.get("source_kind", ""),
                                                "sheet": it.get("sheet_name", "")}))
            if len(matches) >= top_k:
                break
        if len(matches) >= top_k:
            break
    if matches:
        return SourceAdapterResult(FOUND, KIND_EXTRACTED, matches=matches,
                                   trace=[{"adapter": "extracted_body", "matches": len(matches)}])
    status = NOT_FOUND if seen_any else NO_SOURCE
    w = [] if seen_any else ["no_extracted_body: sidecar'ов нет — запустите extract_dataset_bodies_v13.py"]
    return SourceAdapterResult(status, KIND_EXTRACTED, warnings=w)
